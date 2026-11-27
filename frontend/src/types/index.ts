export interface Candidate {
  id: string;
  name: string;
  email: string;
}

export interface SubSkillItem {
  id: number;
  name: string;
  description: string;
  topics: string[];
  difficulty_levels: string[];
}

export interface SkillItem {
  id: string;
  name: string;
  category: string;
  description: string;
  available: boolean;
  sub_skills: SubSkillItem[];
}

export interface SessionStatus {
  id: string;
  candidate_id: string;
  selected_skill: string;
  room_name: string;
  session_status: string;
  terminal_outcome?: string;
  termination_reason?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  duration_seconds: number;
}

export interface StartSessionCredentials {
  session_id: string;
  room_name: string;
  livekit_url: string;
  token: string;
  skill: string;
  status: string;
}

export interface AssessmentResult {
  session_id: string;
  candidate_id: string;
  selected_skill: string;
  session_status: string;
  terminal_outcome: string | null;
  duration_seconds: number;
  started_at: string | null;
  completed_at: string | null;
  summary_metrics: {
    primary_questions_asked?: number;
    questions_answered?: number;
    questions_skipped_permanently?: number;
    questions_revisited?: number;
    timeouts?: number;
    follow_ups_asked?: number;
    off_topic_violations?: number;
  };
  question_history: Record<string, any>;
  candidate_answers: any[];
}
