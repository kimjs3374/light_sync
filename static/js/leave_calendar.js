/* 연차사용촉진 달력 위젯 (직원 셀프지정 / 관리자 서면편집 공용)
 * 대상: .lp-cal[data-promo][data-min][data-max] (선택) data-remaining, data-init
 *   - data-remaining 있으면 잔여일 한도 적용(연차1/반차0.5), 없으면 무제한
 *   - data-init: 프리필 [{date,type}] JSON
 * 연동 요소: #dates-<pid>(hidden), #cnt-<pid>(카운터), #sel-<pid>(선택목록)
 * 전역: window.LP_HOLIDAYS({'YYYY-MM-DD':이름}) 필요
 * API: window.LeaveCalendar.fill(pid, [{date,type}])  window.lpValidate(form,pid)
 */
(function(){
  const WEEK = ['일','월','화','수','목','금','토'];
  const reg = {};   // pid -> {sel:Map, spans:{}, remain:number|null}

  const dval = t => (t === '반차' ? 0.5 : 1.0);
  const ymd = d => d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
  const parse = s => { const [y,m,dd]=s.split('-').map(Number); return new Date(y,m-1,dd); };
  const total = pid => { let t=0; reg[pid].sel.forEach(v=>t+=dval(v)); return t; };
  const HOL = () => window.LP_HOLIDAYS || {};

  function syncSpan(pid, key){
    const sp = reg[pid].spans[key]; if(!sp) return;
    const m = reg[pid].sel;
    if(m.has(key)){ sp.classList.add('sel'); sp.classList.toggle('half', m.get(key)==='반차'); }
    else { sp.classList.remove('sel','half'); }
  }

  function render(pid){
    const R = reg[pid], m = R.sel;
    const list = document.getElementById('sel-'+pid);
    if(list){
      list.innerHTML='';
      Array.from(m.keys()).sort().forEach(key=>{
        const chip=document.createElement('div'); chip.className='lp-chip';
        const d=document.createElement('span'); d.className='d'; d.textContent=key; chip.appendChild(d);
        const tg=document.createElement('span'); tg.className='lp-tg';
        ['연차','반차'].forEach(t=>{
          const b=document.createElement('button'); b.type='button'; b.textContent=t;
          if(m.get(key)===t) b.classList.add('on');
          b.addEventListener('click',()=>{
            if(t===m.get(key)) return;
            if(R.remain!=null && total(pid)-dval(m.get(key))+dval(t) > R.remain+1e-6){
              alert('잔여 연차('+R.remain+'일)를 초과합니다.'); return;
            }
            m.set(key,t); syncSpan(pid,key); render(pid);
          });
          tg.appendChild(b);
        });
        chip.appendChild(tg);
        const rm=document.createElement('button'); rm.type='button'; rm.className='lp-rm'; rm.textContent='×';
        rm.addEventListener('click',()=>{ m.delete(key); syncSpan(pid,key); render(pid); });
        chip.appendChild(rm);
        list.appendChild(chip);
      });
    }
    const t=total(pid), cnt=document.getElementById('cnt-'+pid);
    if(cnt){
      cnt.innerHTML = (R.remain!=null)
        ? '선택 <b>'+(+t.toFixed(1))+'</b>일 / 잔여 '+R.remain+'일'
        : '선택 <b>'+(+t.toFixed(1))+'</b>일';
      cnt.classList.toggle('over', R.remain!=null && t>=R.remain && R.remain>0);
    }
    const hid=document.getElementById('dates-'+pid);
    if(hid) hid.value = JSON.stringify(Array.from(m.entries()).map(([date,type])=>({date,type})));
  }

  function onDay(pid, key){
    const R=reg[pid], m=R.sel;
    if(m.has(key)){ m.delete(key); syncSpan(pid,key); render(pid); return; }
    let type='연차';
    if(R.remain!=null){
      const t=total(pid);
      if(t+1.0<=R.remain+1e-6) type='연차';
      else if(t+0.5<=R.remain+1e-6) type='반차';
      else { alert('잔여 연차('+R.remain+'일)를 모두 선택했습니다.'); return; }
    }
    m.set(key,type); syncSpan(pid,key); render(pid);
  }

  function buildMonth(pid, year, month, minD, maxD){
    const wrap=document.createElement('div'); wrap.className='lp-month';
    const h=document.createElement('div'); h.className='lp-month-h'; h.textContent=year+'년 '+(month+1)+'월'; wrap.appendChild(h);
    const tbl=document.createElement('table'); tbl.className='lp-grid';
    const thead=document.createElement('tr');
    WEEK.forEach((w,i)=>{ const th=document.createElement('th'); th.textContent=w;
      if(i===0) th.style.color='#dc2626'; if(i===6) th.style.color='#2563eb'; thead.appendChild(th); });
    tbl.appendChild(thead);
    const first=new Date(year,month,1), startDow=first.getDay(), dim=new Date(year,month+1,0).getDate();
    let row=document.createElement('tr');
    for(let i=0;i<startDow;i++) row.appendChild(document.createElement('td'));
    for(let day=1;day<=dim;day++){
      if((startDow+day-1)%7===0 && day!==1){ tbl.appendChild(row); row=document.createElement('tr'); }
      const d=new Date(year,month,day), key=ymd(d), dow=d.getDay();
      const td=document.createElement('td'), span=document.createElement('span');
      span.className='lp-day'; span.textContent=day;
      const holName=HOL()[key], inRange=(d>=minD && d<=maxD);
      if(dow===0) span.classList.add('sun'); else if(dow===6) span.classList.add('sat');
      if(holName){ span.classList.add('hol'); span.title=holName; }
      const off=(!inRange || dow===0 || dow===6 || !!holName);
      if(off){ span.classList.add('off'); }
      else { reg[pid].spans[key]=span; span.addEventListener('click',()=>onDay(pid,key)); }
      td.appendChild(span); row.appendChild(td);
    }
    tbl.appendChild(row); wrap.appendChild(tbl); return wrap;
  }

  function init(cal){
    if(cal.dataset.lpInit) return; cal.dataset.lpInit='1';
    const pid=cal.dataset.promo;
    const hasCap = cal.hasAttribute('data-remaining') && cal.dataset.remaining!=='';
    reg[pid]={sel:new Map(), spans:{}, remain: hasCap ? parseFloat(cal.dataset.remaining||'0') : null};
    const minD=parse(cal.dataset.min), maxD=parse(cal.dataset.max);
    let y=minD.getFullYear(), m=minD.getMonth();
    const ey=maxD.getFullYear(), em=maxD.getMonth();
    while(y<ey || (y===ey && m<=em)){ cal.appendChild(buildMonth(pid,y,m,minD,maxD)); m++; if(m>11){m=0;y++;} }
    let initSel=[]; try{ initSel=JSON.parse(cal.dataset.init||'[]'); }catch(e){}
    applyEntries(pid, initSel);
    render(pid);
  }

  function applyEntries(pid, entries){
    const R=reg[pid], m=R.sel;
    (entries||[]).forEach(it=>{
      const key=(it && it.date)?it.date:it;
      const type=(it && it.type==='반차')?'반차':'연차';
      if(R.spans[key]){ m.set(key,type); syncSpan(pid,key); }
    });
  }

  window.LeaveCalendar = {
    fill: function(pid, entries){
      if(!reg[pid]) return;
      reg[pid].sel.forEach((v,k)=>{ const sp=reg[pid].spans[k]; if(sp) sp.classList.remove('sel','half'); });
      reg[pid].sel.clear();
      applyEntries(pid, entries);
      render(pid);
    }
  };

  window.lpValidate = function(form, pid){
    const v=document.getElementById('dates-'+pid).value;
    let arr=[]; try{ arr=JSON.parse(v||'[]'); }catch(e){}
    if(!arr.length){ alert('달력에서 사용 예정일을 1개 이상 선택하세요.'); return false; }
    return true;
  };

  function initAll(){ document.querySelectorAll('.lp-cal').forEach(init); }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', initAll);
  else initAll();
})();
