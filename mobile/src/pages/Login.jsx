import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const login = useAuth((s) => s.login);

  const handleSubmit = async (e) => {
    e?.preventDefault?.();
    setError('');
    setLoading(true);
    try {
      await login(username, password);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <h1 style={styles.title}>MAGNATECH</h1>
        <p style={styles.subtitle}>Light-Sync ERP</p>

        <form onSubmit={handleSubmit} style={styles.form}>
          {error && <div style={styles.error}>{error}</div>}
          <input
            type="text" placeholder="아이디" value={username}
            onChange={(e) => setUsername(e.target.value)}
            style={styles.input} autoCapitalize="none" autoComplete="username"
          />
          <input
            type="password" placeholder="비밀번호" value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={styles.input} autoComplete="current-password"
          />
          <button type="submit" disabled={loading} style={styles.button} onClick={handleSubmit}>
            {loading ? '로그인 중...' : '로그인'}
          </button>
        </form>
      </div>
    </div>
  );
}

const styles = {
  container: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    minHeight: '100vh', padding: 20, background: '#1a1d21',
  },
  card: { width: '100%', maxWidth: 340, textAlign: 'center' },
  title: { fontSize: 24, fontWeight: 700, color: '#f2f3f5', letterSpacing: 1 },
  subtitle: { fontSize: 13, color: '#8b8d91', marginTop: 4, marginBottom: 32 },
  form: { display: 'flex', flexDirection: 'column', gap: 10 },
  input: {
    padding: '12px 14px', borderRadius: 6,
    border: '1px solid #35383d', background: '#222529',
    color: '#f2f3f5', fontSize: 14,
  },
  button: {
    padding: 12, borderRadius: 6, border: 'none',
    background: '#4a9eff', color: '#fff',
    fontSize: 14, fontWeight: 600, cursor: 'pointer', marginTop: 6,
  },
  error: {
    padding: '8px 12px', borderRadius: 6,
    background: 'rgba(242,63,67,0.12)', color: '#f23f43',
    fontSize: 13, textAlign: 'center',
  },
};
