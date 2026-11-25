import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE_URL || (typeof window !== 'undefined' && window.location.port === '5173' ? 'http://localhost:8000' : '');

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
  getSkills: async () => {
    const res = await api.get('/api/skills');
    return res.data.skills;
  },
  createSession: async (skill: string = 'Python') => {
    const res = await api.post('/api/sessions', { skill });
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
