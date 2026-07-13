/* 연차사용촉진 달력 위젯 — 모바일 전용 (월 단위 페이징 + 탭 순환 선택)
 * 대상: .lpm-cal[data-promo][data-min][data-max] (선택) data-remaining, data-init
 *   - 탭 1회: 연차(1일) → 탭 2회: 반차(0.5일) → 탭 3회: 해제
 *   - data-remaining 있으면 잔여일 한도 적용(연차1/반차0.5), 초과 시 자동으로 반차 우선
 *   - data-init: 프리필 [{date,type}] JSON
 * 연동 요소: #dates-<pid>(hidden), #cnt-<pid>(카운터), #sel-<pid>(선택목록)
 * 전역: window.LP_HOLIDAYS({'YYYY-MM-DD':이름}) 필요
 */
(function(){
  const WEEK = ['일','월','화','수','목','금','토'];
  const reg = {};   // pid -> {sel, remain, minD, maxD, cur, grid, title, prev, next}
  const dval = t => (t === '반차' ? 0.5 : 1.0);
  const pad = n => String(n).padStart(2,'0');
  const ymd = d => d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
  const parse = s => { const [y,m,dd]=s.split('-').map(Number); return new Date(y,m-1,dd); };
  const total = pid => { let t=0; reg[pid].sel.forEach(v=>t+=dval(v)); return +t.toFixed(1); };
  const HOL = () => window.LP_HOLIDAYS || {};

  function onDay(pid, key){
    const R=reg[pid], m=R.sel;
    if(!m.has(key)){
      let type='연차';
      if(R.remain!=null){
        const t=total(pid);
        if(t+1.0<=R.remain+1e-6) type='연차';
        else if(t+0.5<=R.remain+1e-6) type='반차';
        else { alert('잔여 연차('+R.remain+'일)를 모두 선택했습니다.'); return; }
      }
      m.set(key,type);
    } else if(m.get(key)==='연차'){
      m.set(key,'반차');             // 연차 → 반차 (잔여 감소이므로 항상 허용)
    } else {
      m.delete(key);                 // 반차 → 해제
    }
    renderGrid(pid); renderState(pid);
  }

  function renderGrid(pid){
    const R=reg[pid], y=R.cur.getFullYear(), mo=R.cur.getMonth();
    R.title.textContent = y+'년 '+(mo+1)+'월';
    R.prev.disabled = (y<R.minD.getFullYear() || (y===R.minD.getFullYear() && mo<=R.minD.getMonth()));
    R.next.disabled = (y>R.maxD.getFullYear() || (y===R.maxD.getFullYear() && mo>=R.maxD.getMonth()));
    R.grid.innerHTML='';
    const first=new Date(y,mo,1), startDow=first.getDay(), dim=new Date(y,mo+1,0).getDate();
    for(let i=0;i<startDow;i++){ const e=document.createElement('div'); e.className='lpm-day empty'; R.grid.appendChild(e); }
    for(let day=1;day<=dim;day++){
      const d=new Date(y,mo,day), key=ymd(d), dow=d.getDay();
      const cell=document.createElement('div'); cell.className='lpm-day';
      const num=document.createElement('span'); num.textContent=day; cell.appendChild(num);
      const holName=HOL()[key], inRange=(d>=R.minD && d<=R.maxD);
      if(dow===0) cell.classList.add('sun'); else if(dow===6) cell.classList.add('sat');
      if(holName){ cell.classList.add('hol');
        const hn=document.createElement('span'); hn.className='hn'; hn.textContent=holName; cell.appendChild(hn); }
      const off=(!inRange || dow===0 || dow===6 || !!holName);
      if(off){ cell.classList.add('off'); }
      else {
        if(R.sel.has(key)){ cell.classList.add('sel'); if(R.sel.get(key)==='반차') cell.classList.add('half');
          const tg=document.createElement('span'); tg.className='tag'; tg.textContent=R.sel.get(key); cell.appendChild(tg); }
        cell.addEventListener('click',()=>onDay(pid,key));
      }
      R.grid.appendChild(cell);
    }
  }

  function renderState(pid){
    const R=reg[pid], m=R.sel;
    const list=document.getElementById('sel-'+pid);
    if(list){
      list.innerHTML='';
      Array.from(m.keys()).sort().forEach(key=>{
        const chip=document.createElement('div'); chip.className='lpm-chip';
        const d=document.createElement('span'); d.className='d'; d.textContent=key;
        const t=document.createElement('span'); t.className='t'+(m.get(key)==='반차'?' half':''); t.textContent=m.get(key);
        const rm=document.createElement('button'); rm.type='button'; rm.className='rm'; rm.textContent='×';
        rm.addEventListener('click',()=>{ m.delete(key); renderGrid(pid); renderState(pid); });
        chip.appendChild(d); chip.appendChild(t); chip.appendChild(rm);
        list.appendChild(chip);
      });
    }
    const t=total(pid), cnt=document.getElementById('cnt-'+pid);
    if(cnt){
      cnt.innerHTML = (R.remain!=null)
        ? '선택 <b>'+t+'</b>일 / 잔여 '+R.remain+'일'
        : '선택 <b>'+t+'</b>일';
      cnt.classList.toggle('over', R.remain!=null && t>=R.remain && R.remain>0);
    }
    const hid=document.getElementById('dates-'+pid);
    if(hid) hid.value = JSON.stringify(Array.from(m.entries()).map(([date,type])=>({date,type})));
  }

  function init(cal){
    if(cal.dataset.lpInit) return; cal.dataset.lpInit='1';
    const pid=cal.dataset.promo;
    const hasCap = cal.hasAttribute('data-remaining') && cal.dataset.remaining!=='';
    const minD=parse(cal.dataset.min), maxD=parse(cal.dataset.max);
    // 헤더(이전/다음) + 요일행 + 그리드 DOM 구성
    const head=document.createElement('div'); head.className='lpm-head';
    const prev=document.createElement('button'); prev.type='button'; prev.className='lpm-nav'; prev.textContent='‹';
    const title=document.createElement('div'); title.className='lpm-title';
    const next=document.createElement('button'); next.type='button'; next.className='lpm-nav'; next.textContent='›';
    head.appendChild(prev); head.appendChild(title); head.appendChild(next); cal.appendChild(head);
    const wk=document.createElement('div'); wk.className='lpm-week';
    WEEK.forEach((w,i)=>{ const s=document.createElement('span'); s.textContent=w;
      if(i===0) s.classList.add('sun'); if(i===6) s.classList.add('sat'); wk.appendChild(s); });
    cal.appendChild(wk);
    const grid=document.createElement('div'); grid.className='lpm-grid'; cal.appendChild(grid);

    reg[pid]={ sel:new Map(), remain: hasCap ? parseFloat(cal.dataset.remaining||'0') : null,
               minD, maxD, cur:new Date(minD.getFullYear(),minD.getMonth(),1),
               grid, title, prev, next };
    prev.addEventListener('click',()=>{ if(prev.disabled) return; reg[pid].cur.setMonth(reg[pid].cur.getMonth()-1); renderGrid(pid); });
    next.addEventListener('click',()=>{ if(next.disabled) return; reg[pid].cur.setMonth(reg[pid].cur.getMonth()+1); renderGrid(pid); });

    let initSel=[]; try{ initSel=JSON.parse(cal.dataset.init||'[]'); }catch(e){}
    (initSel||[]).forEach(it=>{
      const key=(it && it.date)?it.date:it;
      const type=(it && it.type==='반차')?'반차':'연차';
      if(key) reg[pid].sel.set(key,type);
    });
    renderGrid(pid); renderState(pid);
  }

  window.lpmValidate = function(form, pid){
    const v=document.getElementById('dates-'+pid).value;
    let arr=[]; try{ arr=JSON.parse(v||'[]'); }catch(e){}
    if(!arr.length){ alert('달력에서 사용 예정일을 1개 이상 선택하세요.'); return false; }
    return true;
  };

  function initAll(){ document.querySelectorAll('.lpm-cal').forEach(init); }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', initAll);
  else initAll();
})();
