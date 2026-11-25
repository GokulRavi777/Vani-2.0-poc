import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Bot, Lock, Mail, ArrowRight, AlertCircle } from 'lucide-react';

export const LoginPage: React.FC = () => {
  const [email, setEmail] = useState('candidate@vani.ai');
  const [password, setPassword] = useState('candidate123');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      await login(email, password);
      navigate('/skills');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Invalid email or password. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col justify-center items-center px-4">
      <div className="w-full max-w-md bg-white border border-slate-200 rounded-2xl p-8 shadow-xl shadow-slate-200/50">
        <div className="flex flex-col items-center mb-8">
          <div className="w-20 h-20 rounded-2xl bg-indigo-50 border border-indigo-100 flex items-center justify-center mb-4 p-2 overflow-hidden shadow-lg shadow-indigo-100">
            <img src="/vani-avatar.png" alt="VANI AI" className="w-full h-full object-contain" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">VANI 2.0 Interview Portal</h1>
          <p className="text-slate-500 text-sm mt-1">Autonomous Conversational AI Technical Interviewer</p>
        </div>

        {error && (
          <div className="mb-6 p-4 rounded-xl bg-red-50 border border-red-200 flex items-center gap-3 text-red-600 text-sm">
            <AlertCircle className="w-5 h-5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-2">
              Candidate Email
            </label>
            <div className="relative">
              <Mail className="w-5 h-5 text-slate-400 absolute left-3.5 top-3" />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full bg-slate-50 border border-slate-200 rounded-xl px-11 py-2.5 text-slate-900 placeholder-slate-400 focus:outline-none focus:bg-white focus:border-indigo-600 focus:ring-1 focus:ring-indigo-600 transition text-sm"
                placeholder="name@example.com"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-2">
              Password
            </label>
            <div className="relative">
              <Lock className="w-5 h-5 text-slate-400 absolute left-3.5 top-3" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full bg-slate-50 border border-slate-200 rounded-xl px-11 py-2.5 text-slate-900 placeholder-slate-400 focus:outline-none focus:bg-white focus:border-indigo-600 focus:ring-1 focus:ring-indigo-600 transition text-sm"
                placeholder="••••••••"
              />
            </div>
            <p className="text-xs text-slate-400 mt-1">Default demo credentials pre-filled.</p>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-medium py-3 rounded-xl flex items-center justify-center gap-2 transition duration-200 shadow-lg shadow-indigo-600/20 mt-2 cursor-pointer"
          >
            {isLoading ? (
              <span className="inline-block w-5 h-5 border-2 border-white/20 border-t-white rounded-full animate-spin" />
            ) : (
              <>
                <span>Sign In to Assessment</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>
      </div>
    </div>
  );
};
