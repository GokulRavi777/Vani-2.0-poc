import React, { useState, useEffect, useRef } from 'react';
import { useParams, useLocation, useNavigate } from 'react-router-dom';
import {
  Room, RoomEvent, Track, RemoteParticipant, RemoteTrackPublication, RemoteTrack, ConnectionState
} from 'livekit-client';
import { assessmentService } from '../services/api';
import { StartSessionCredentials } from '../types';
import {
  Mic, MicOff, PhoneOff, Bot, Radio, Wifi, Volume2, VolumeX,
  User, Sparkles, Clock, AlertCircle, ShieldAlert
} from 'lucide-react';

interface TranscriptItem {
  id: string;
  sender: 'Vani' | 'Candidate' | string;
  text: string;
  time: string;
}

export const InterviewPage: React.FC = () => {
  const { sessionId } = useParams<{ sessionId: string }>();
  const location = useLocation();
  const navigate = useNavigate();

  const [credentials, setCredentials] = useState<StartSessionCredentials | null>(
    location.state?.credentials || null
  );

  const [room, setRoom] = useState<Room | null>(null);
  const [connectionState, setConnectionState] = useState<string>('Connecting...');
  const [isMicMuted, setIsMicMuted] = useState<boolean>(false);
  const [interviewerSpeaking, setInterviewerSpeaking] = useState<boolean>(false);
  const [candidateSpeaking, setCandidateSpeaking] = useState<boolean>(false);
  const [audioPlaybackBlocked, setAudioPlaybackBlocked] = useState<boolean>(false);
  const [transcriptLogs, setTranscriptLogs] = useState<TranscriptItem[]>([]);
  const [isEnding, setIsEnding] = useState<boolean>(false);

  const audioContainerRef = useRef<HTMLDivElement>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const pollerRef = useRef<any>(null);

  // Auto-scroll transcript when new items arrive
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcriptLogs]);

  // Initialize or fetch credentials if missing
  useEffect(() => {
    const initCreds = async () => {
      if (!credentials && sessionId) {
        try {
          const creds = await assessmentService.startSession(sessionId);
          setCredentials(creds);
        } catch (err) {
          console.error('Error fetching credentials for session:', err);
          navigate(`/skills`);
        }
      }
    };
    initCreds();
  }, [sessionId, credentials, navigate]);

  // Connect to LiveKit Room and bind WebRTC audio & data handlers
  useEffect(() => {
    if (!credentials) return;

    let isSubscribed = true;

    const lkRoom = new Room({
      adaptiveStream: true,
      dynacast: true,
      audioCaptureDefaults: {
        autoGainControl: true,
        echoCancellation: true,
        noiseSuppression: true,
      },
    });

    const attachAudioTrack = (track: RemoteTrack) => {
      if (track.kind === Track.Kind.Audio) {
        try {
          const audioElement = track.attach();
          audioElement.autoplay = true;
          audioElement.volume = 1.0;
          audioElement.play().catch((err) => {
            console.warn('Browser media autoplay prevented:', err);
            if (isSubscribed) setAudioPlaybackBlocked(true);
          });
          if (audioContainerRef.current && !audioContainerRef.current.contains(audioElement)) {
            audioContainerRef.current.appendChild(audioElement);
          }
        } catch (e) {
          console.error('Error attaching remote audio track:', e);
        }
      }
    };

    // 1. Register event handlers BEFORE connecting so no early events are missed
    lkRoom.on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
      if (!isSubscribed) return;
      if (state === ConnectionState.Connected) {
        setConnectionState('Connected');
      } else if (state === ConnectionState.Connecting) {
        setConnectionState('Connecting...');
      } else if (state === ConnectionState.Reconnecting) {
        setConnectionState('Reconnecting...');
      } else if (state === ConnectionState.Disconnected) {
        setConnectionState('Disconnected');
      }
    });

    lkRoom.on(RoomEvent.TrackSubscribed, (track: RemoteTrack, publication: RemoteTrackPublication, participant: RemoteParticipant) => {
      console.log('LiveKit TrackSubscribed:', track.kind, participant.identity);
      attachAudioTrack(track);
    });

    lkRoom.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
      track.detach();
    });

    lkRoom.on(RoomEvent.AudioPlaybackStatusChanged, () => {
      if (isSubscribed) {
        setAudioPlaybackBlocked(!lkRoom.canPlaybackAudio);
      }
    });

    lkRoom.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
      if (!isSubscribed) return;
      const isLocalSpeaking = speakers.some((s) => s.isLocal);
      const isRemoteSpeaking = speakers.some((s) => !s.isLocal);
      setCandidateSpeaking(isLocalSpeaking);
      setInterviewerSpeaking(isRemoteSpeaking);
    });

    lkRoom.on(RoomEvent.DataReceived, (payload: Uint8Array) => {
      try {
        const text = new TextDecoder().decode(payload);
        const data = JSON.parse(text);
        if (data.type === 'transcript' && data.text) {
          const newItem: TranscriptItem = {
            id: `${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
            sender: data.sender || 'Vani',
            text: data.text,
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          };
          setTranscriptLogs((prev) => [...prev, newItem]);
        }
      } catch (e) {
        // Non-JSON data or raw bytes
      }
    });

    lkRoom.on(RoomEvent.Disconnected, () => {
      if (isSubscribed) setConnectionState('Disconnected');
    });

    // 2. Connect to the LiveKit Cloud Room
    const connectToRoom = async () => {
      try {
        setConnectionState('Connecting to LiveKit Room...');
        await lkRoom.connect(credentials.livekit_url, credentials.token);

        if (!isSubscribed) {
          lkRoom.disconnect();
          return;
        }

        setConnectionState('Connected');
        setRoom(lkRoom);

        // Attach any audio tracks already subscribed during handshake
        lkRoom.remoteParticipants.forEach((participant) => {
          participant.trackPublications.forEach((pub) => {
            if (pub.track) {
              attachAudioTrack(pub.track);
            }
          });
        });

        // Publish local microphone track
        try {
          await lkRoom.localParticipant.setMicrophoneEnabled(true);
          setIsMicMuted(false);
        } catch (micErr) {
          console.error('Error enabling candidate microphone:', micErr);
          setIsMicMuted(true);
        }

        // Verify audio playback readiness
        if (!lkRoom.canPlaybackAudio) {
          setAudioPlaybackBlocked(true);
        }
      } catch (err) {
        console.error('LiveKit connection error:', err);
        if (isSubscribed) setConnectionState('Failed to connect');
      }
    };

    connectToRoom();

    // User gesture listener to automatically unlock audio on any interaction
    const unlockAudio = () => {
      if (lkRoom && !lkRoom.canPlaybackAudio) {
        lkRoom.startAudio().then(() => {
          if (isSubscribed) setAudioPlaybackBlocked(false);
        }).catch(() => {});
      }
    };
    window.addEventListener('click', unlockAudio);

    return () => {
      isSubscribed = false;
      window.removeEventListener('click', unlockAudio);
      lkRoom.disconnect();
    };
  }, [credentials]);

  // Periodic Poller to observe server-side session completion or timeout
  useEffect(() => {
    if (!sessionId) return;

    pollerRef.current = setInterval(async () => {
      try {
        const sess = await assessmentService.getSessionStatus(sessionId);
        if (
          sess.session_status === 'COMPLETED' ||
          sess.session_status === 'TERMINATED' ||
          sess.session_status === 'CLOSED'
        ) {
          if (pollerRef.current) clearInterval(pollerRef.current);
          if (room) room.disconnect();
          navigate(`/assessment/completed/${sessionId}`, {
            state: {
              outcome: sess.terminal_outcome || sess.session_status,
              duration: sess.duration_seconds,
            },
          });
        }
      } catch (e) {
        // Transient network error
      }
    }, 2500);

    return () => {
      if (pollerRef.current) clearInterval(pollerRef.current);
    };
  }, [sessionId, room, navigate]);

  const toggleMute = async () => {
    if (!room) return;
    const nextState = !isMicMuted;
    await room.localParticipant.setMicrophoneEnabled(!nextState);
    setIsMicMuted(nextState);
  };

  const handleStartAudio = async () => {
    if (room) {
      await room.startAudio();
      setAudioPlaybackBlocked(false);
    }
  };

  const handleEndInterview = async () => {
    if (!sessionId) return;
    setIsEnding(true);
    try {
      await assessmentService.terminateSession(sessionId);
      if (room) room.disconnect();
      navigate(`/assessment/completed/${sessionId}`, {
        state: { outcome: 'TERMINATED_BY_CANDIDATE' },
      });
    } catch (e) {
      console.error('Error terminating interview:', e);
      setIsEnding(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col select-none">
      {/* Offscreen audio rendering container (avoids display:none autoplay restrictions) */}
      <div
        ref={audioContainerRef}
        style={{ position: 'fixed', top: -9999, left: -9999, width: 1, height: 1, pointerEvents: 'none' }}
      />

      {/* Top Header */}
      <header className="border-b border-slate-200 bg-white/90 backdrop-blur px-6 py-3.5 flex justify-between items-center z-10 sticky top-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl overflow-hidden bg-indigo-50 border border-indigo-100 flex items-center justify-center p-1 shadow-sm">
            <img src="/vani-avatar.png" alt="VANI" className="w-full h-full object-contain" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-semibold text-sm text-slate-900">VANI 2.0 Interviewer</h1>
              <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-indigo-50 text-indigo-700 border border-indigo-200">
                Python Domain
              </span>
            </div>
            <p className="text-xs text-slate-500">Technical Assessment Room: {sessionId}</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-slate-100 border border-slate-200 text-xs">
            <span
              className={`w-2 h-2 rounded-full ${
                connectionState === 'Connected'
                  ? 'bg-emerald-500 animate-pulse'
                  : connectionState.includes('Connecting')
                  ? 'bg-amber-500 animate-ping'
                  : 'bg-red-500'
              }`}
            />
            <span className="text-slate-700 font-medium">{connectionState}</span>
          </div>

          <button
            onClick={handleEndInterview}
            disabled={isEnding}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-red-50 border border-red-200 hover:bg-red-100 text-red-600 text-xs font-semibold rounded-lg transition cursor-pointer"
          >
            <PhoneOff className="w-3.5 h-3.5" />
            <span>{isEnding ? 'Ending...' : 'End Interview'}</span>
          </button>
        </div>
      </header>

      {/* Audio Playback Warning Banner */}
      {audioPlaybackBlocked && (
        <div className="bg-amber-50 border-b border-amber-200 px-6 py-2.5 flex items-center justify-between text-xs text-amber-800">
          <div className="flex items-center gap-2">
            <VolumeX className="w-4 h-4 text-amber-600 animate-pulse" />
            <span>Audio playback is currently paused by browser security policy. Click to hear VANI speak.</span>
          </div>
          <button
            onClick={handleStartAudio}
            className="px-3 py-1 bg-amber-600 hover:bg-amber-700 text-white font-bold rounded text-xs transition cursor-pointer"
          >
            Unmute Audio
          </button>
        </div>
      )}

      {/* Main Workspace: Left Stage + Right Transcript */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 overflow-hidden">
        {/* Left: Speaker Visualizer & Stage */}
        <main className="lg:col-span-7 flex flex-col justify-center items-center p-8 relative border-r border-slate-200 bg-white/40">
          <div className="flex flex-col items-center max-w-sm w-full text-center">
            {/* Avatar Pulse Rings */}
            <div className="relative mb-6">
              <div
                className={`w-36 h-36 rounded-full overflow-hidden flex items-center justify-center p-3 transition-all duration-300 ${
                  interviewerSpeaking
                    ? 'bg-indigo-50 ring-8 ring-indigo-200 shadow-2xl shadow-indigo-100 scale-105 border-2 border-indigo-500'
                    : candidateSpeaking
                    ? 'bg-emerald-50 ring-8 ring-emerald-200 shadow-2xl shadow-emerald-100 border-2 border-emerald-500'
                    : 'bg-white border-2 border-slate-200 shadow-md'
                }`}
              >
                <img
                  src="/vani-avatar.png"
                  alt="VANI"
                  className={`w-full h-full object-contain transition-transform duration-300 ${
                    interviewerSpeaking
                      ? 'scale-110 drop-shadow-[0_0_15px_rgba(99,102,241,0.5)]'
                      : candidateSpeaking
                      ? 'opacity-80 scale-95'
                      : 'scale-100 opacity-95'
                  }`}
                />
              </div>

              {interviewerSpeaking && (
                <div className="absolute -inset-4 rounded-full border-2 border-indigo-400/50 animate-ping pointer-events-none" />
              )}
              {candidateSpeaking && (
                <div className="absolute -inset-4 rounded-full border-2 border-emerald-400/50 animate-ping pointer-events-none" />
              )}
            </div>

            {/* Speaking Status Caption */}
            <h3 className="text-xl font-bold text-slate-900 tracking-tight">
              {interviewerSpeaking
                ? 'Vani is speaking...'
                : candidateSpeaking
                ? 'Candidate is speaking...'
                : 'Listening for candidate responses...'}
            </h3>

            <p className="text-xs text-slate-500 mt-2 max-w-xs leading-relaxed">
              Speak naturally through your microphone. VANI listens in real-time and adapts to clarifications.
            </p>

            {/* Dynamic Sound Wave Visualizer */}
            <div className="flex items-center justify-center gap-1.5 h-10 mt-6">
              {[35, 65, 95, 55, 80, 45, 90, 60, 30].map((h, i) => (
                <span
                  key={i}
                  style={{
                    height: interviewerSpeaking || candidateSpeaking ? `${h}%` : '20%',
                  }}
                  className={`w-1.5 rounded-full transition-all duration-150 ${
                    interviewerSpeaking
                      ? 'bg-indigo-600'
                      : candidateSpeaking
                      ? 'bg-emerald-600'
                      : 'bg-slate-300'
                  }`}
                />
              ))}
            </div>
          </div>
        </main>

        {/* Right: Live Transcript View */}
        <aside className="lg:col-span-5 flex flex-col bg-slate-50/60 overflow-hidden">
          <div className="px-5 py-3.5 border-b border-slate-200 flex justify-between items-center bg-white/80">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-indigo-600" />
              <h2 className="text-xs font-semibold text-slate-800 uppercase tracking-wider">
                Live Conversation Transcript
              </h2>
            </div>
            <div className="flex items-center gap-1 text-[11px] text-slate-500">
              <Clock className="w-3.5 h-3.5" />
              <span>Real-time</span>
            </div>
          </div>

          <div className="flex-1 p-4 overflow-y-auto space-y-3.5">
            {transcriptLogs.length === 0 ? (
              <div className="h-full flex flex-col justify-center items-center text-center p-6 text-slate-400">
                <img src="/vani-avatar.png" alt="VANI" className="w-16 h-16 mb-2 object-contain opacity-50" />
                <p className="text-xs font-medium text-slate-600">Interview in progress</p>
                <p className="text-[11px] text-slate-500 mt-1 max-w-xs">
                  Spoken questions and answers will appear here as you interact with VANI.
                </p>
              </div>
            ) : (
              transcriptLogs.map((item) => {
                const isVani = item.sender.toLowerCase().includes('vani');
                return (
                  <div
                    key={item.id}
                    className={`flex flex-col ${isVani ? 'items-start' : 'items-end'}`}
                  >
                    <div className="flex items-center gap-1.5 mb-1 px-1 text-[10px] text-slate-500">
                      {isVani ? (
                        <>
                          <img src="/vani-avatar.png" alt="VANI" className="w-3.5 h-3.5 object-contain" />
                          <span className="font-semibold text-indigo-600">VANI</span>
                        </>
                      ) : (
                        <>
                          <span className="font-semibold text-emerald-600">You</span>
                          <User className="w-3 h-3 text-emerald-600" />
                        </>
                      )}
                      <span className="text-slate-400">{item.time}</span>
                    </div>

                    <div
                      className={`max-w-[88%] rounded-2xl px-4 py-2.5 text-xs leading-relaxed shadow-sm ${
                        isVani
                          ? 'bg-white text-slate-800 border border-slate-200 rounded-tl-sm'
                          : 'bg-indigo-600 text-white rounded-tr-sm'
                      }`}
                    >
                      {item.text}
                    </div>
                  </div>
                );
              })
            )}
            <div ref={transcriptEndRef} />
          </div>
        </aside>
      </div>

      {/* Bottom Footer Controls */}
      <footer className="border-t border-slate-200 bg-white/90 backdrop-blur p-4 flex justify-center items-center gap-4 z-10">
        <button
          onClick={toggleMute}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold border transition cursor-pointer ${
            isMicMuted
              ? 'bg-red-50 border-red-200 text-red-600 hover:bg-red-100'
              : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50 shadow-sm'
          }`}
        >
          {isMicMuted ? (
            <MicOff className="w-4 h-4 text-red-600" />
          ) : (
            <Mic className="w-4 h-4 text-emerald-600" />
          )}
          <span>{isMicMuted ? 'Microphone Muted' : 'Microphone Live'}</span>
        </button>

        {audioPlaybackBlocked && (
          <button
            onClick={handleStartAudio}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-amber-50 border border-amber-200 text-amber-700 hover:bg-amber-100 transition shadow-sm cursor-pointer"
          >
            <Volume2 className="w-4 h-4" />
            <span>Enable Sound</span>
          </button>
        )}
      </footer>
    </div>
  );
};
