import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { assessmentService } from '../services/api';
import { SkillItem } from '../types';
import { Code2, CheckCircle2, ArrowRight, LogOut, ChevronDown, ChevronRight, Layers } from 'lucide-react';

export const SkillSelectionPage: React.FC = () => {
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [expandedMother, setExpandedMother] = useState<string>('Python');
  const [selectedSkill, setSelectedSkill] = useState<string>('Python');
  const [selectedSubSkill, setSelectedSubSkill] = useState<string | null>('Python Core');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { candidate, logout } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    const loadSkills = async () => {
      try {
        const data: SkillItem[] = await assessmentService.getSkills();
        setSkills(data);
        const defaultMother = data.find((s) => s.name === 'Python') || data[0];
        if (defaultMother) {
          setExpandedMother(defaultMother.name);
          setSelectedSkill(defaultMother.name);
          setSelectedSubSkill(defaultMother.sub_skills?.[0]?.name || null);
        }
      } catch (err) {
        console.error('Error fetching skills:', err);
        setError('Failed to load skills from server.');
      }
    };
    loadSkills();
  }, []);

  const handleToggleMother = (mother: SkillItem) => {
    const isAlreadyExpanded = expandedMother === mother.name;
    setExpandedMother(isAlreadyExpanded ? '' : mother.name);
    if (selectedSkill !== mother.name) {
      setSelectedSkill(mother.name);
      setSelectedSubSkill(mother.sub_skills?.[0]?.name || null);
    }
  };

  const handleSelectSubSkill = (motherName: string, subSkillName: string) => {
    setSelectedSkill(motherName);
    setSelectedSubSkill(subSkillName);
  };

  const handleContinue = async () => {
    setIsSubmitting(true);
    setError(null);
    try {
      const session = await assessmentService.createSession(selectedSkill, selectedSubSkill);
      navigate('/assessment/setup', {
        state: {
          sessionId: session.id,
          skill: selectedSkill,
          subSkill: selectedSubSkill,
        },
      });
    } catch (err: any) {
      console.error('Error creating assessment session:', err);
      setError(err.response?.data?.detail || 'Could not create assessment session.');
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
          <span className="text-sm text-slate-600">
            Candidate: <strong className="text-slate-900">{candidate?.name}</strong>
          </span>
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
            Choose a mother skill to expand its specializations, then select the exact skill for your voice interview.
          </p>
        </div>

        {error && (
          <div className="mb-6 p-4 rounded-xl bg-red-50 border border-red-200 text-red-600 text-sm">
            {error}
          </div>
        )}

        {/* Mother Skill -> Sub-Skill Tree */}
        <div className="space-y-4 mb-8">
          {skills.map((mother) => {
            const isExpanded = expandedMother === mother.name;
            const isMotherActive = selectedSkill === mother.name;
            return (
              <div
                key={mother.id}
                className={`rounded-2xl border transition-all bg-white shadow-sm overflow-hidden ${
                  isMotherActive
                    ? 'border-indigo-400 ring-2 ring-indigo-500/10'
                    : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                {/* Mother Skill Row */}
                <button
                  type="button"
                  onClick={() => handleToggleMother(mother)}
                  className="w-full p-5 flex items-start justify-between text-left hover:bg-slate-50/70 transition cursor-pointer"
                >
                  <div className="flex items-start gap-4">
                    <div
                      className={`p-3 rounded-xl border ${
                        isMotherActive
                          ? 'bg-indigo-50 border-indigo-200 text-indigo-600'
                          : 'bg-slate-100 border-slate-200 text-slate-500'
                      }`}
                    >
                      <Code2 className="w-6 h-6" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2.5 flex-wrap">
                        <h3 className="font-semibold text-lg text-slate-900">{mother.name}</h3>
                        <span className="text-xs px-2.5 py-0.5 rounded-full bg-slate-100 border border-slate-200 text-slate-700 font-medium">
                          {mother.sub_skills?.length || 0} Specializations
                        </span>
                      </div>
                      <p className="text-slate-600 text-sm mt-1 max-w-2xl">{mother.description}</p>
                    </div>
                  </div>
                  <div className="pt-2 text-slate-400">
                    {isExpanded ? <ChevronDown className="w-5 h-5" /> : <ChevronRight className="w-5 h-5" />}
                  </div>
                </button>

                {/* Sub-Skill Subtree */}
                {isExpanded && mother.sub_skills && mother.sub_skills.length > 0 && (
                  <div className="px-6 pb-6 pt-1 bg-slate-50/60 border-t border-slate-100">
                    <div className="pl-5 border-l-2 border-indigo-200 space-y-3 mt-3">
                      {mother.sub_skills.map((sub) => {
                        const isSubSelected =
                          selectedSkill === mother.name && selectedSubSkill === sub.name;
                        return (
                          <div
                            key={sub.id}
                            onClick={() => handleSelectSubSkill(mother.name, sub.name)}
                            className={`p-4 rounded-xl border transition-all cursor-pointer flex items-start justify-between ${
                              isSubSelected
                                ? 'bg-indigo-50/90 border-indigo-500 ring-1 ring-indigo-500/20 shadow-sm'
                                : 'bg-white border-slate-200 hover:border-indigo-300'
                            }`}
                          >
                            <div className="flex items-start gap-3">
                              <Layers
                                className={`w-5 h-5 mt-0.5 flex-shrink-0 ${
                                  isSubSelected ? 'text-indigo-600' : 'text-slate-400'
                                }`}
                              />
                              <div>
                                <div className="flex items-center gap-2 flex-wrap">
                                  <h4 className="font-semibold text-slate-900 text-sm">{sub.name}</h4>
                                  {sub.difficulty_levels?.length > 0 && (
                                    <span className="text-[11px] px-2 py-0.5 rounded-md bg-slate-100 text-slate-600 font-medium">
                                      {sub.difficulty_levels.join(' / ')}
                                    </span>
                                  )}
                                </div>
                                <p className="text-slate-600 text-xs mt-1">{sub.description}</p>
                                {sub.topics?.length > 0 && (
                                  <div className="flex flex-wrap gap-1.5 mt-2.5">
                                    {sub.topics.map((topic) => (
                                      <span
                                        key={topic}
                                        className="text-[11px] px-2 py-0.5 rounded-full bg-white border border-slate-200 text-slate-600"
                                      >
                                        {topic}
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>
                            </div>
                            <CheckCircle2
                              className={`w-5 h-5 flex-shrink-0 mt-0.5 ${
                                isSubSelected ? 'text-indigo-600' : 'text-slate-300'
                              }`}
                            />
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Selection Summary & Continue Button */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-2">
          <div className="text-sm text-slate-600">
            Selected track:{' '}
            <strong className="text-slate-900">
              {selectedSkill}
              {selectedSubSkill ? ` → ${selectedSubSkill}` : ''}
            </strong>
          </div>
          <button
            onClick={handleContinue}
            disabled={!selectedSkill || isSubmitting}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-medium px-8 py-3 rounded-xl flex items-center justify-center gap-2 transition duration-200 shadow-lg shadow-indigo-600/20 cursor-pointer"
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
