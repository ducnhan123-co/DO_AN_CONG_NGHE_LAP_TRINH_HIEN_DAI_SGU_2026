const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const code=fs.readFileSync('frontend/config.js','utf8');

function launch({url,force=false,answers=[]}={}){
  const storage=new Map();
  const calls=[];
  const source={};
  const origin='https://sgu-pdf-rag-frontend.onrender.com';
  const loc={origin,href:origin+'/index.html'+(url?'?api='+encodeURIComponent(url):''),
    search:url?'?api='+encodeURIComponent(url):'',reload(){}};
  const context={
    window:source,location:loc,URL,URLSearchParams,Headers,Request,
    sessionStorage:{
      getItem:k=>storage.get(k)||null,
      setItem:(k,v)=>storage.set(k,v),
      removeItem:k=>storage.delete(k),
    },
    prompt:()=>answers.shift()??null,alert:()=>{},
    btoa:s=>Buffer.from(s,'utf8').toString('base64'),
  };
  source.location=loc;
  source.MATCHPDF_FORCE_ORIGIN=force;
  source.fetch=async (u,o)=>{calls.push({u,o}); return {ok:true}};
  vm.runInNewContext(code,context);
  return {source,calls,storage};
}
test('Render frontend targets Mac URL with Basic auth only on API requests', async()=>{
  const r=launch({url:'https://example.trycloudflare.com',answers:['demo','secret123']});
  assert.equal(r.source.MATCHPDF_API_BASE,'https://example.trycloudflare.com');
  assert.equal(r.source.MATCHPDF_LIB_BASE,'https://example.trycloudflare.com');
  await r.source.fetch('https://example.trycloudflare.com/api/upload',{method:'POST'});
  await r.source.fetch('https://external.example.com/v1/health');
  assert.equal(r.calls[0].o.headers.get('authorization'),
               'Basic '+Buffer.from('demo:secret123').toString('base64'));
  assert.equal(r.calls[1].o,undefined);
});
test('same-origin Mac frontend ignores remote overrides',()=>{
  const r=launch({url:'https://example.trycloudflare.com',force:true});
  assert.equal(r.source.MATCHPDF_API_BASE,'https://sgu-pdf-rag-frontend.onrender.com');
  assert.equal(Object.keys(r.source.MATCHPDF_API_AUTH).length,0);
});
test('rejects a non-HTTPS remote API',()=>{
  const r=launch({url:'http://evil.example.com',answers:[]});
  assert.equal(r.source.MATCHPDF_API_BASE,
    'https://do-an-cong-nghe-lap-trinh-hien-dai-sgu.onrender.com');
});
