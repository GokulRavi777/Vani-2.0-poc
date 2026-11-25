import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { assessmentService } from '../services/api';
import { SkillItem } from '../types';
import { Code2, CheckCircle2, ArrowRight, LogOut } from 'lucide-react';

export const SkillSelectionPage: React.FC = () => {
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [selectedSkill, setSelectedSkill] = useState<string>('Python');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { candidate, logout } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    const loadSkills = async () => {
      try {
        const data = await assessmentService.getSkills();
        setSkills(data);
      } catch (err) {
        console.error('Error fetching skills:', err);
      }
    };
    loadSkills();
  }, []);

  const handleContinue = async () => {
    setIsSubmitting(true);
    try {
      const session = await assessmentService.createSession(selectedSkill);
      // Navigate to assessment setup with session ID
      navigate('/assessment/setup', { state: { sessionId: session.id, skill: selectedSkill } });
    } catch (err) {
      console.error('Error creating assessment session:', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col">
      {/* Header */}
      <header className="border-b border-slate-200 bg-white/80 backdrop-blur px-6 py-4 flex justify-between items-center sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center">
            <Code2 className="w-5 h-5 text-indigo-600" />
          </div>
          <span className="font-semibold text-lg text-slate-900">VANI 2.0</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-slate-600">Candidate: <strong className="text-slate-900">{candidate?.name}</strong></span>
          <button
            onClick={logout}
            className="text-slate-400 hover:text-slate-700 p-2 rounded-lg hover:bg-slate-100 transition cursor-pointer"
            title="Log out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-4xl w-full mx-auto p-6 md:p-12 flex flex-col justify-center">
        <div className="mb-8">
          <h2 className="text-3xl font-bold text-slate-900 tracking-tight">Select Assessment Domain</h2>
          <p className="text-slate-600 mt-2">
            Please confirm your technical skill to begin your conversational voice interview.
          </p>
        </div>

        {/* Skill Card List */}
        <div className="grid grid-cols-1 gap-4 mb-8">
          {skills.map((skill) => {
            const isSelected = selectedSkill === skill.name;
            return (
              <div
                key={skill.id}
                onClick={() => setSelectedSkill(skill.name)}
                className={`p-6 rounded-2xl border transition-all cursor-pointer flex items-start justify-between shadow-sm ${
                  isSelected
                    ? 'bg-indigo-50/70 border-indigo-500 ring-2 ring-indigo-500/20 shadow-indigo-100/50'
                    : 'bg-white border-slate-200 hover:border-slate-300 hover:shadow-md'
                }`}
              >
                <div className="flex items-start gap-4">
                  <div className={`p-3 rounded-xl border ${
                    isSelected
                      ? 'bg-indigo-100/80 border-indigo-200 text-indigo-600'
                      : 'bg-slate-100 border-slate-200 text-slate-500'
                  }`}>
                    <Code2 className="w-6 h-6" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-lg text-slate-900">{skill.name}</h3>
                      <span className="text-xs px-2.5 py-0.5 rounded-full bg-slate-100 border border-slate-200 text-slate-700 font-medium">
                        {skill.category}
                      </span>
                    </div>
                    <p className="text-slate-600 text-sm mt-1 max-w-xl">{skill.description}</p>
                  </div>
                </div>

                <div className="flex items-center pt-1">
                  <CheckCircle2 className={`w-6 h-6 ${isSelected ? 'text-indigo-600' : 'text-slate-300'}`} />
                </div>
              </div>
            );
          })}
        </div>

        {/* Action Button */}
        <div className="flex justify-end">
          <button
            onClick={handleContinue}
            disabled={!selectedSkill || isSubmitting}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-medium px-8 py-3 rounded-xl flex items-center gap-2 transition duration-200 shadow-lg shadow-indigo-600/20 cursor-pointer"
          >
            {isSubmitting ? (
              <span className="inline-block w-5 h-5 border-2 border-white/20 border-t-white rounded-full animate-spin" />
            ) : (
              <>
                <span>Continue to Assessment Setup</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </div>
      </main>
    </div>
  );
};
