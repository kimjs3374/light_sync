import { useNavigate } from 'react-router-dom';
import ListPage from '../components/ListPage';

function dday(dateStr) {
  if (!dateStr) return null;
  const diff = Math.ceil((new Date(dateStr) - new Date()) / 86400000);
  if (diff < 0) return { text: `D+${Math.abs(diff)}`, color: 'red' };
  if (diff <= 7) return { text: `D-${diff}`, color: 'orange' };
  return null;
}

function Badge({ text, color = 'gray' }) {
  if (!text) return null;
  return <span className={`badge badge-${color}`}>{text}</span>;
}

export default function Projects() {
  const nav = useNavigate();
  return (
    <ListPage
      icon="#" title="현장관리" endpoint="/projects" dataKey="projects"
      defaultParams={{ status: '계약' }}
      filters={[{
        key: 'status', label: '상태',
        options: [
          { value: '계약', label: '진행중' },
          { value: '납품완료', label: '완료' },
          { value: '설계/영업', label: '설계/영업' },
        ],
      }]}
      stats={(d) => {
        const ps = d.projects || [];
        const overdue = ps.filter(p => dday(p.delivery_date)?.color === 'red').length;
        return [
          { label: '전체', value: ps.length },
          { label: '지연', value: overdue, color: 'red' },
        ];
      }}
      onItemClick={(p) => nav(`/projects/${p.id}`)}
      renderItem={(p) => {
        const dd = dday(p.delivery_date);
        return (
          <>
            <div className="indicator" style={{ background: dd?.color === 'red' ? 'var(--red)' : dd?.color === 'orange' ? 'var(--orange)' : 'var(--border)' }} />
            <div className="msg-body">
              <div className="msg-top">
                <span className="msg-id">{p.project_no}</span>
                <span className="msg-date">{p.delivery_date}</span>
                {dd && <Badge text={dd.text} color={dd.color} />}
                <Badge text={p.payment_status} color={
                  p.payment_status === '입금완료' ? 'green' :
                  p.payment_status === '미청구' ? 'orange' : 'blue'
                } />
              </div>
              <div className="msg-title">{p.name || p.contract_name}</div>
              <div className="msg-meta">
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{p.ordering_org || p.short_name}</span>
                {p.contract_amount > 0 && <span className="money">{Number(p.contract_amount).toLocaleString()}원</span>}
              </div>
            </div>
          </>
        );
      }}
    />
  );
}
