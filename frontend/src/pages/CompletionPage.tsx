import React, { useEffect, useState } from 'react';
import { useParams, useLocation, useNavigate } from 'react-router-dom';
import { assessmentService } from '../services/api';
import { AssessmentResult } from '../types';
import {
  CheckCircle2, XCircle, AlertTriangle, ArrowRight, Clock, Award,
  HelpCircle, RefreshCw, Bot
} from 'lucide-react';

export const CompletionPage: React.FC = () => {
  const { sessionId } = useParams<{ sessionId: string }>();
  const location = useLocation();
  const navigate = useNavigate();

  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const initialOutcome = location.state?.outcome;

  useEffect(() => {
    const fetchResults = async () => {
      if (!sessionId) return;
      try {
        const data = await assessmentService.getResults(sessionId);
        setResult(data);
      } catch (err) {
        console.error('Error retrieving assessment results:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchResults();
  }, [sessionId]);

  const outcome = result?.terminal_outcome || initialOutcome || 'COMPLETED';

  const isSuccess = outcome === 'COMPLETED';
  const isVoluntaryTerm = outcome === 'TERMINATED_BY_CANDIDATE';
  const isGuardrailTerm = outcome === 'TERMINATED_BY_GUARDRAIL';

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col justify-center items-center p-6">
      <div className="max-w-2xl w-full bg-white border border-slate-200 rounded-2xl p-8 shadow-xl shadow-slate-200/50">
        {/* Status Header */}
        <div className="flex flex-col items-center text-center mb-8">
          <div className={`w-20 h-20 rounded-2xl flex items-center justify-center mb-4 border ${
            isSuccess
              ? 'bg-emerald-50 border-emerald-200 text-emerald-600'
              : isVoluntaryTerm
              ? 'bg-amber-50 border-amber-200 text-amber-600'
              : 'bg-red-50 border-red-200 text-red-600'
          }`}>
            {isSuccess ? (
              <CheckCircle2 className="w-10 h-10" />
            ) : isVoluntaryTerm ? (
              <AlertTriangle className="w-10 h-10" />
            ) : (
              <XCircle className="w-10 h-10" />
            )}
          </div>

          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            {isSuccess
              ? 'Assessment Completed'
              : isVoluntaryTerm
              ? 'Interview Concluded by Candidate'
              : 'Session Terminated'}
          </h1>

          <p className="text-sm text-slate-500 mt-1 max-w-md">
            {isSuccess
              ? 'Thank you for participating! Your voice interview has been completed and your responses are safely recorded.'
              : isVoluntaryTerm
              ? 'You voluntarily ended this assessment session. Your recorded turns up to this point have been preserved.'
              : 'This assessment was terminated in accordance with interview guardrails.'}
          </p>
        </div>

        {/* Assessment Summary Metrics */}
        {result && (
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-5 mb-8 space-y-4">
            <h3 className="text-xs font-semibold text-slate-700 uppercase tracking-wider flex items-center gap-2">
              <Award className="w-4 h-4 text-indigo-600" />
              Assessment Session Summary
            </h3>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div className="bg-white p-3 rounded-lg border border-slate-200 shadow-sm">
                <span className="text-xs text-slate-500">Skill Domain</span>
                <p className="text-sm font-bold text-slate-900 mt-0.5">{result.selected_skill}</p>
              </div>

              <div className="bg-white p-3 rounded-lg border border-slate-200 shadow-sm">
                <span className="text-xs text-slate-500">Duration</span>
                <p className="text-sm font-bold text-slate-900 mt-0.5">
                  {Math.round(result.duration_seconds || 0)}s
                </p>
              </div>

              <div className="bg-white p-3 rounded-lg border border-slate-200 shadow-sm">
                <span className="text-xs text-slate-500">Questions Answered</span>
                <p className="text-sm font-bold text-emerald-600 mt-0.5">
                  {result.summary_metrics?.questions_answered ?? 'Recorded'}
                </p>
              </div>

              <div className="bg-white p-3 rounded-lg border border-slate-200 shadow-sm">
                <span className="text-xs text-slate-500">Terminal Outcome</span>
                <p className="text-xs font-bold text-indigo-600 mt-1 truncate">{outcome}</p>
              </div>
            </div>
          </div>
        )}

        {/* Footer Actions */}
        <div className="flex justify-between items-center pt-2">
          <button
            onClick={() => navigate('/skills')}
            className="text-xs font-semibold text-slate-500 hover:text-slate-800 transition flex items-center gap-1.5 cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Return to Domains</span>
          </button>

          <button
            onClick={() => navigate('/login')}
            className="bg-indigo-600 hover:bg-indigo-700 text-white font-medium px-6 py-2.5 rounded-xl text-sm transition shadow-sm cursor-pointer"
          >
            Sign Out
          </button>
        </div>
      </div>
    </div>
  );
};
