/* Offline review protocol; no network requests or automatic human labels. */
function reviewBinding(data) {
  return {schema_version:'video-temporal-review-v2', clip_id:data.clip_id,
    media_sha:data.input_sha256, config_digest:data.config_digest, report_digest:data.report_digest};
}
function validateReviewRows(rows, data) {
  if (!Array.isArray(rows) || !rows.length) throw new Error('文件没有已完成的复核条目。');
  const binding=reviewBinding(data), events=new Set(data.events.map(e=>e.event_id)), seen=new Set();
  const fields=[...Object.keys(binding),'event_id','decision','evidence'].sort().join(',');
  for (const row of rows) {
    if (!row || Object.keys(row).sort().join(',')!==fields) throw new Error('复核文件字段不匹配。');
    for (const [key,value] of Object.entries(binding)) if(row[key]!==value) throw new Error('复核属于另一条视频、事件或规则；未导入任何条目。');
    if(!events.has(row.event_id)||seen.has(row.event_id)) throw new Error('事件编号不存在或重复。');
    seen.add(row.event_id);
    if(!['confirmed','intentional','uncertain'].includes(row.decision)) throw new Error('结论值无效。');
    if(typeof row.evidence!=='string'||!row.evidence.trim()||row.evidence.length>4000) throw new Error('每项复核都需要 1–4000 字的具体依据。');
  }
  return rows;
}
function sourceToPlayback(sourcePts, sourceStart) { return sourcePts-sourceStart; }
if (typeof module!=='undefined') module.exports={reviewBinding,validateReviewRows,sourceToPlayback};
if (typeof document!=='undefined') {
  const data=window.AUDIT_DATA, binding=reviewBinding(data), video=document.getElementById('video');
  const status=document.getElementById('status'), key='video-audit-v2:'+data.report_digest;
  let mediaUrl=null, previewLoading=false;
  async function bindPackagedPreview() {
    if(mediaUrl)URL.revokeObjectURL(mediaUrl);mediaUrl=null;
    if(!['http:','https:'].includes(location.protocol)) {
      video.src=data.preview.file;return;
    }
    previewLoading=true;
    document.getElementById('media-status').textContent='正在读取并核验预览；随后使用本机 Blob 支持可靠跳转，无需服务器 Range。';
    try {
      const head=await fetch(data.preview.file,{method:'HEAD',cache:'no-store'});
      if(head.ok&&head.headers.get('Accept-Ranges')==='bytes') {
        video.src=data.preview.file;
        document.getElementById('media-status').textContent='本机服务支持视频 Range，已启用按需播放；预览摘要与逐帧时间映射见报告绑定。';
        return;
      }
      const maxBytes=64*1024*1024;
      const declaredSize=Number(head.headers.get('Content-Length'));
      if(declaredSize>maxBytes)throw new Error('预览超过 64 MiB；请使用 video_temporal_audit serve 服务支持按需跳转，或选择本机原片。');
      const response=await fetch(data.preview.file,{cache:'no-store'});
      if(!response.ok)throw new Error('预览读取失败：HTTP '+response.status);
      const reader=response.body.getReader(),chunks=[];let total=0;
      while(true){const {value,done}=await reader.read();if(done)break;total+=value.byteLength;if(total>maxBytes){await reader.cancel();throw new Error('预览超过 64 MiB，已停止缓存；请使用 serve 服务。');}chunks.push(value);}
      const bytes=new Uint8Array(total);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
      if(!crypto.subtle)throw new Error('当前环境无法计算摘要，请使用 localhost 或本机文件打开报告。');
      const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
      if(hash!==data.preview.sha256)throw new Error('预览 SHA-256 不匹配，已停止播放；请重新生成报告。');
      mediaUrl=URL.createObjectURL(new Blob([bytes],{type:'video/mp4'}));video.src=mediaUrl;
      document.getElementById('media-status').textContent='预览 SHA-256 已核验；本机 Blob 播放已启用，可定位回看。文件不会上传。';
    }catch(error){video.removeAttribute('src');video.load();document.getElementById('media-status').textContent=error.message;}
    finally{previewLoading=false;}
  }
  function notice(message,error=false) { status.textContent=message; status.classList.toggle('error',error); }
  function draftRows() { return data.events.map(e=>({...binding,event_id:e.event_id,
      decision:document.getElementById('decision-'+e.event_id).value,
      evidence:document.getElementById('evidence-'+e.event_id).value})); }
  function applyRows(rows) { for(const row of rows) { const select=document.getElementById('decision-'+row.event_id), note=document.getElementById('evidence-'+row.event_id); if(select&&note){ select.value=row.decision;note.value=row.evidence; } } }
  function saveDraft() { try { localStorage.setItem(key,JSON.stringify({binding,rows:draftRows()}));notice('本机草稿已保存。请导出 JSONL 留存或通过 CLI 生成正式复核版报告。'); } catch(e){notice('浏览器未允许本机草稿保存。请导出 JSONL 留存。',true);} }
  applyRows(data.human_reviews||[]);
  try {
    const saved=JSON.parse(localStorage.getItem(key)||'null');
    if(saved && JSON.stringify(saved.binding)===JSON.stringify(binding) && Array.isArray(saved.rows)) {
      const eventIds=new Set(data.events.map(e=>e.event_id));
      if(saved.rows.every(r=>eventIds.has(r.event_id)&&['','confirmed','intentional','uncertain'].includes(r.decision)&&typeof r.evidence==='string')) {
        applyRows(saved.rows);notice('已恢复本机草稿。正式复核版仍需导出并导回 CLI。');
      }
    }
  } catch(e) { notice('未能恢复草稿；可导回之前导出的 JSONL。',true); }
  document.querySelectorAll('select,textarea').forEach(el=>el.addEventListener('input',saveDraft));
  document.getElementById('save-draft').addEventListener('click',saveDraft);
  video.addEventListener('timeupdate',()=> {document.getElementById('playhead').textContent=`播放器位置 ${video.currentTime.toFixed(6)} 秒 · 源 PTS ${(video.currentTime+data.source_start_s).toFixed(6)} 秒`;});
  video.addEventListener('error',()=> { document.getElementById('media-status').textContent='浏览器无法播放该视频；请在本机播放器按源 PTS 回看。播放失败不能记为视频质量缺陷。'; });
  document.querySelectorAll('[data-event]').forEach(button=>button.addEventListener('click',()=> {
    const event=data.events.find(e=>e.event_id===button.dataset.event);
    const seek=Math.max(0,sourceToPlayback(event.start_s,data.source_start_s)-.5);
    if(previewLoading){document.getElementById('media-status').textContent='预览仍在核验，完成后请再点回放。';return;}
    const label=document.getElementById('media-status');
    const play=()=>{
      video.pause();label.textContent=`正在定位 ${event.event_id}：目标播放 ${seek.toFixed(6)} 秒。`;
      let finished=false;
      const verify=()=>{
        if(finished)return;finished=true;video.removeEventListener('seeked',verify);
        if(Math.abs(video.currentTime-seek)>.05){label.textContent='播放器未定位到目标时刻；请检查本机媒体或重新加载预览。';return;}
        label.textContent=`已定位 ${event.event_id}：播放 ${video.currentTime.toFixed(6)} 秒；事件源 PTS ${event.start_s.toFixed(6)} 秒。`;
        video.play().catch(()=>{label.textContent+=' 请点击播放器的播放按钮继续。';});
      };
      video.addEventListener('seeked',verify);
      video.currentTime=seek;
      if(Math.abs(video.currentTime-seek)<=.05&&!video.seeking)verify();
      setTimeout(()=>{if(!finished){finished=true;video.removeEventListener('seeked',verify);label.textContent='尚未确认播放器跳转，请重新加载附带预览或选择已核验原片；不能将此状态记成已定位。';}},3000);
    };
    if(video.readyState>=1)play();else video.addEventListener('loadedmetadata',play,{once:true});
    document.querySelectorAll('.event').forEach(el=>el.classList.toggle('selected',el.id===event.event_id));
  }));
  document.getElementById('export-reviews').addEventListener('click',()=> {
    try {
      const all=draftRows(), selected=all.filter(r=>r.decision);
      validateReviewRows(selected,data);
      const payload=selected.map(r=>JSON.stringify(r)).join('\n')+'\n';
      const blob=new Blob([payload],{type:'application/x-ndjson;charset=utf-8'}), url=URL.createObjectURL(blob), a=document.createElement('a');
      a.href=url;a.download=data.clip_id+'_'+data.report_digest.slice(0,8)+'_reviews.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      notice(`已导出 ${selected.length}/${all.length} 项；未选择的 ${all.length-selected.length} 项仍待复核。文件导出不代表已通过 CLI 导入。`);
    }catch(e){notice(e.message,true);}
  });
  document.getElementById('import-reviews').addEventListener('change',async event=> {
    try { const file=event.target.files[0];if(!file)return;const rows=(await file.text()).split(/\r?\n/).filter(line=>line.trim()).map(line=>JSON.parse(line));validateReviewRows(rows,data);applyRows(rows);saveDraft();notice(`已校验并导回 ${rows.length} 项本机草稿；正式报告请运行 import-reviews。`); }catch(e){notice(e.message,true);}finally{event.target.value='';}
  });
  document.getElementById('media-file').addEventListener('change',async event=> {
    const file=event.target.files[0];if(!file)return;
    try {
      if(!crypto.subtle)throw new Error('本浏览器无法计算文件摘要。请通过 localhost 打开报告，或使用已核验的附带预览。');
      const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer()))].map(x=>x.toString(16).padStart(2,'0')).join('');
      if(hash!==data.input_sha256&&hash!==data.preview.sha256)throw new Error('所选文件 SHA-256 不匹配；播放器继续使用原来的视频。');
      if(mediaUrl)URL.revokeObjectURL(mediaUrl);mediaUrl=URL.createObjectURL(file);video.src=mediaUrl;
      document.getElementById('media-status').textContent='已核验媒体 SHA-256；使用本机文件，不上传。';
    }catch(e){document.getElementById('media-status').textContent=e.message;}
  });
  document.getElementById('restore-preview').addEventListener('click',bindPackagedPreview);
  bindPackagedPreview();
}
