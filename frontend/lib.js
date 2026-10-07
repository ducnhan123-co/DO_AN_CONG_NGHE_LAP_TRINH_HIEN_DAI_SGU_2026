/* Client dùng chung cho Library API (cùng backend, cổng 8000). Không bao giờ ném lỗi: trả {ok,status,data}; status 0 = server tắt. */
(function(){
  const BASE=(window.MATCHPDF_API_BASE||'http://127.0.0.1:8000').replace(/\/$/,'')+'/api';
  let mem=null;
  function cid(){
    try{ let v=localStorage.getItem('matchpdf_client_id');
      if(!v){ v=newId(); localStorage.setItem('matchpdf_client_id',v); } return v; }
    catch(e){ return mem||(mem=newId()); }
  }
  function newId(){ const raw=(window.crypto&&crypto.randomUUID)?crypto.randomUUID():(Date.now().toString(36)+Math.random().toString(36).slice(2)+Math.random().toString(36).slice(2));
    return 'c'+raw.replace(/[^A-Za-z0-9_-]/g,''); }
  async function call(method,path,body){
    try{
      const r=await fetch(BASE+path,{method,headers:Object.assign({'X-Client-Id':cid()},body!==undefined?{'Content-Type':'application/json'}:{}),
        body:body!==undefined?JSON.stringify(body):undefined,signal:AbortSignal.timeout(10000)});
      let data=null; try{ data=await r.json(); }catch(e){}
      return {ok:r.ok,status:r.status,data};
    }catch(e){ return {ok:false,status:0,data:null}; }
  }
  async function blob(path){
    try{ const r=await fetch(BASE+path,{headers:{'X-Client-Id':cid()}}); if(!r.ok) return {ok:false,status:r.status}; return {ok:true,blob:await r.blob()}; }
    catch(e){ return {ok:false,status:0}; }
  }
  window.LIB={cid,blob,fileUrl:id=>BASE+'/doc/'+id+'/file',
    get:p=>call('GET',p), post:(p,b)=>call('POST',p,b===undefined?{}:b), put:(p,b)=>call('PUT',p,b),
    patch:(p,b)=>call('PATCH',p,b), del:p=>call('DELETE',p)};
})();