"""Protocol v2 adapters. Stable IDs, explicit versions, pooled independent readers."""
from __future__ import annotations
import json
import re
import threading
import time
import uuid

import httpx


class StreamingBackend:
    def __init__(self, backend, collection, ef=128):
        if not re.fullmatch(r'fb2_[a-z0-9_]{1,40}', collection):
            raise ValueError('V2 collections must use the dedicated fb2_ namespace')
        self.backend, self.collection, self.ef = backend, collection, ef
        self.class_name = 'F'+collection.replace('_','')
        self.url = {'qdrant':'http://127.0.0.1:16333','weaviate':'http://127.0.0.1:18080'}.get(backend)
        self.http = httpx.Client(base_url=self.url or 'http://localhost',timeout=15,
                                 limits=httpx.Limits(max_connections=128,max_keepalive_connections=128))
        self.local=threading.local();self.connections=[];self.lock=threading.Lock()

    def _id(self,key):
        return str(uuid.uuid5(uuid.NAMESPACE_URL,self.collection+':'+str(key)))

    def request(self,method,path,body=None,missing=False):
        r=self.http.request(method,path,json=body)
        if missing and r.status_code==404:return None
        if r.is_error:
            raise RuntimeError(f"{self.backend} HTTP {r.status_code} {method} {path}: {r.text[:2000]}")
        return r.json() if r.content else {}

    def connection(self):
        conn=getattr(self.local,'conn',None)
        if conn is None:
            import psycopg
            conn=psycopg.connect('postgresql://postgres:postgres@127.0.0.1:15432/freshness',autocommit=True)
            conn.execute('SET statement_timeout = 15000')
            conn.execute(f'SET hnsw.ef_search = {int(self.ef)}')
            # Explicit ANN track; EXPLAIN is retained to verify the effective path.
            conn.execute('SET enable_seqscan = off')
            self.local.conn=conn
            with self.lock:self.connections.append(conn)
        return conn

    def create(self,dimensions):
        if self.backend=='qdrant':
            self.request('PUT',f'/collections/{self.collection}',{
                'vectors':{'size':dimensions,'distance':'Cosine'},
                'hnsw_config':{'m':16,'ef_construct':128,'full_scan_threshold':10},
                'optimizers_config':{'indexing_threshold':0}})
            self.request('PUT',f'/collections/{self.collection}/index?wait=true',{'field_name':'cohort','field_schema':'keyword'})
        elif self.backend=='weaviate':
            self.request('POST','/v1/schema',{
                'class':self.class_name,'vectorizer':'none','vectorIndexType':'hnsw',
                'vectorIndexConfig':{'distance':'cosine','efConstruction':128,'maxConnections':16,'ef':self.ef,'flatSearchCutoff':0},
                'properties':[{'name':'doc_id','dataType':['text'],'tokenization':'field'},
                              {'name':'version','dataType':['int']},
                              {'name':'cohort','dataType':['text'],'tokenization':'field'},
                              {'name':'text','dataType':['text'],'indexSearchable':False,'indexFilterable':False}]})
        elif self.backend=='pgvector':
            conn=self.connection();conn.execute('CREATE EXTENSION IF NOT EXISTS vector')
            conn.execute(f'CREATE TABLE {self.collection} (id text PRIMARY KEY, version integer NOT NULL, cohort text NOT NULL, text text NOT NULL, embedding vector({int(dimensions)}) NOT NULL)')
        else:raise ValueError(self.backend)

    @staticmethod
    def payload(doc):
        return {'doc_id':str(doc['id']),'version':int(doc['version']),'cohort':doc['cohort'],'text':doc.get('text','')}

    def bulk(self,docs,vectors):
        if self.backend=='qdrant':
            self.request('PUT',f'/collections/{self.collection}/points?wait=true',{'points':[
                {'id':self._id(d['id']),'vector':v.tolist(),'payload':self.payload(d)} for d,v in zip(docs,vectors)]})
        elif self.backend=='weaviate':
            body=self.request('POST','/v1/batch/objects',{'objects':[
                {'class':self.class_name,'id':self._id(d['id']),'vector':v.tolist(),'properties':self.payload(d)} for d,v in zip(docs,vectors)]})
            for item in body:
                if item.get('result',{}).get('errors'):raise RuntimeError(str(item['result']['errors']))
        else:
            with self.connection().cursor().copy(f'COPY {self.collection} (id,version,cohort,text,embedding) FROM STDIN') as copy:
                for d,v in zip(docs,vectors):copy.write_row((str(d['id']),d['version'],d['cohort'],d.get('text',''),self.vector(v)))

    def finish_load(self):
        if self.backend=='qdrant':
            self.request('PATCH',f'/collections/{self.collection}',{'optimizers_config':{'indexing_threshold':1024}})
        elif self.backend=='pgvector':
            conn=self.connection()
            conn.execute('SET statement_timeout = 300000')
            conn.execute('SET maintenance_work_mem = \'512MB\'')
            conn.execute(f'CREATE INDEX {self.collection}_hnsw ON {self.collection} USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=128)')
            conn.execute(f'ANALYZE {self.collection}')
            conn.execute('SET statement_timeout = 15000')

    @staticmethod
    def vector(v):return '['+','.join(str(float(x)) for x in v)+']'

    def write(self,operation,doc,vector):
        key=str(doc['id']);point=self._id(key)
        if self.backend=='qdrant':
            if operation=='delete':self.request('POST',f'/collections/{self.collection}/points/delete?wait=true',{'points':[point]})
            else:self.request('PUT',f'/collections/{self.collection}/points?wait=true',{'points':[{'id':point,'vector':vector.tolist(),'payload':self.payload(doc)}]})
        elif self.backend=='weaviate':
            path=f'/v1/objects/{self.class_name}/{point}'
            if operation=='delete':self.request('DELETE',path)
            else:self.request('PUT' if operation=='update' else 'POST',path if operation=='update' else '/v1/objects',
                             {'class':self.class_name,'id':point,'vector':vector.tolist(),'properties':self.payload(doc)})
        else:
            conn=self.connection()
            if operation=='delete':conn.execute(f'DELETE FROM {self.collection} WHERE id=%s',(key,))
            else:conn.execute(f'INSERT INTO {self.collection} VALUES (%s,%s,%s,%s,%s::vector) ON CONFLICT (id) DO UPDATE SET version=EXCLUDED.version,cohort=EXCLUDED.cohort,text=EXCLUDED.text,embedding=EXCLUDED.embedding',
                              (key,doc['version'],doc['cohort'],doc.get('text',''),self.vector(vector)))

    def get(self,key):
        if self.backend=='qdrant':
            body=self.request('GET',f'/collections/{self.collection}/points/{self._id(key)}',missing=True)
            return body['result']['payload'] if body else None
        if self.backend=='weaviate':
            body=self.request('GET',f'/v1/objects/{self.class_name}/{self._id(key)}',missing=True)
            return body.get('properties') if body else None
        row=self.connection().execute(f'SELECT id,version,cohort FROM {self.collection} WHERE id=%s',(str(key),)).fetchone()
        return {'doc_id':row[0],'version':row[1],'cohort':row[2]} if row else None

    def search(self,vector,k=10,static=False):
        if self.backend=='qdrant':
            body={'query':vector.tolist(),'limit':k,'with_payload':['doc_id','version','cohort'],
                  'params':{'hnsw_ef':self.ef,'exact':False}}
            if static:body['filter']={'must':[{'key':'cohort','match':{'value':'static'}}]}
            return [p['payload'] for p in self.request('POST',f'/collections/{self.collection}/points/query',body)['result']['points']]
        if self.backend=='weaviate':
            where=', where: {path: ["cohort"], operator: Equal, valueText: "static"}' if static else ''
            query='{ Get { '+self.class_name+'(nearVector: {vector: '+json.dumps(vector.tolist())+'}, limit: '+str(k)+where+') { doc_id version cohort } } }'
            body=self.request('POST','/v1/graphql',{'query':query})
            if body.get('errors'):raise RuntimeError(str(body['errors']))
            return body['data']['Get'][self.class_name] or []
        where="WHERE cohort='static'" if static else ''
        rows=self.connection().execute(f'SELECT id,version,cohort FROM {self.collection} {where} ORDER BY embedding <=> %s::vector LIMIT %s',(self.vector(vector),k)).fetchall()
        return [{'doc_id':r[0],'version':r[1],'cohort':r[2]} for r in rows]

    def count(self):
        if self.backend=='qdrant':return self.request('POST',f'/collections/{self.collection}/points/count',{'exact':True})['result']['count']
        if self.backend=='weaviate':
            body=self.request('POST','/v1/graphql',{'query':'{ Aggregate { '+self.class_name+' { meta { count } } } }'})
            return body['data']['Aggregate'][self.class_name][0]['meta']['count']
        return self.connection().execute(f'SELECT count(*) FROM {self.collection}').fetchone()[0]

    def info(self,vector=None):
        if self.backend=='qdrant':return {'version':self.request('GET','/')['version'],'collection':self.request('GET',f'/collections/{self.collection}')['result'],'ack':'wait=true','transport':'HTTP REST, pooled httpx'}
        if self.backend=='weaviate':return {'version':self.request('GET','/v1/meta')['version'],'schema':self.request('GET',f'/v1/schema/{self.class_name}'),'shards':self.request('GET',f'/v1/schema/{self.class_name}/shards'),'ack':'synchronous indexing, object PUT/POST/DELETE','transport':'HTTP REST writes + GraphQL search, pooled httpx'}
        conn=self.connection()
        info={'version':conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0],
              'postgres':conn.execute('SELECT version()').fetchone()[0], 'ef_search':self.ef,'ack':'autocommit, READ COMMITTED','transport':'psycopg, connection per worker'}
        if vector is not None:info['query_plan']=conn.execute(f'EXPLAIN (FORMAT JSON) SELECT id FROM {self.collection} WHERE cohort=\'static\' ORDER BY embedding <=> %s::vector LIMIT 10',(self.vector(vector),)).fetchone()[0]
        return info

    def drop(self):
        if self.backend=='qdrant':self.request('DELETE',f'/collections/{self.collection}')
        elif self.backend=='weaviate':self.request('DELETE',f'/v1/schema/{self.class_name}')
        else:self.connection().execute(f'DROP TABLE {self.collection}')

    def close(self):
        self.http.close()
        for conn in self.connections:conn.close()
