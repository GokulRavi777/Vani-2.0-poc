import axios from 'axios';

let rawBase = (import.meta.env.VITE_API_BASE_URL || '').trim();
if (rawBase && !rawBase.startsWith('http://') && !rawBase.startsWith('https://')) {
  rawBase = `https://${rawBase}`;
}
if (rawBase.endsWith('/')) {
  rawBase = rawBase.slice(0, -1);
}

export const API_BASE = rawBase || (typeof window !== 'undefined' && window.location.port === '5173' ? 'http://localhost:8000' : '');

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('vani_token');
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const authService = {
  login: async (email: string, password: string) => {
    const res = await api.post('/api/auth/login', { email, password });
    return res.data;
  },
  getMe: async () => {
    const res = await api.get('/api/auth/me');
    return res.data;
  },
};

export const assessmentService = {
  getSkills: async (query?: string) => {
    const res = await api.get('/api/skills', {
      params: query && query.trim() ? { q: query.trim() } : undefined,
    });
    return res.data.skills;
  },
  createSession: async (skill: string = 'Python', subSkill?: string | null) => {
    const res = await api.post('/api/sessions', { skill, sub_skill: subSkill || null });
    return res.data;
  },
  startSession: async (sessionId: string) => {
    const res = await api.post(`/api/sessions/${sessionId}/start`);
    return res.data;
  },
  getSessionStatus: async (sessionId: string) => {
    const res = await api.get(`/api/sessions/${sessionId}`);
    return res.data;
  },
  terminateSession: async (sessionId: string) => {
    const res = await api.post(`/api/sessions/${sessionId}/terminate`);
    return res.data;
  },
  getResults: async (sessionId: string) => {
    const res = await api.get(`/api/results/${sessionId}`);
    return res.data;
  },
};

export default api;
