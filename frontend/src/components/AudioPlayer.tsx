"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  DotsIcon,
  PauseIcon,
  PlayIcon,
  VolumeIcon,
} from "@/components/icons";

/**
 * A themed audio player.
 *
 * `<audio controls>` is drawn by the browser and cannot be styled, so on a dark
 * page it sits there as a grey slab in the wrong font. This is the same element
 * with its controls hidden and the transport rebuilt: play, a scrubber you can
 * drag or arrow through, mute, and a speed control — a twenty-three second clip
 * is worth skipping through when you have five minutes to fill.
 *
 * Keyboard: Space or Enter to play, arrows to seek five seconds, Home and End
 * to jump. The scrubber is a real slider role, so a screen reader announces
 * position rather than a nameless div.
 */

const SPEEDS = [1, 1.25, 1.5, 2];

function clock(seconds: number): string {
  if (!Number.isFinite(seconds)) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function AudioPlayer({
  src,
  onError,
}: {
  src: string;
  onError?: () => void;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);

  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState(1);
  const [menuOpen, setMenuOpen] = useState(false);

  const progress = duration > 0 ? current / duration : 0;

  const seekTo = useCallback((fraction: number) => {
    const audio = audioRef.current;
    if (!audio || !Number.isFinite(audio.duration)) return;
    const next = Math.min(Math.max(fraction, 0), 1) * audio.duration;
    audio.currentTime = next;
    setCurrent(next);
  }, []);

  function toggle() {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) void audio.play();
    else audio.pause();
  }

  // Dragging continues outside the track, the way a real scrubber does.
  const startScrub = useCallback(
    (e: React.PointerEvent) => {
      const track = trackRef.current;
      if (!track) return;

      const move = (clientX: number) => {
        const rect = track.getBoundingClientRect();
        seekTo((clientX - rect.left) / rect.width);
      };
      move(e.clientX);

      const onMove = (ev: PointerEvent) => move(ev.clientX);
      const onUp = () => {
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", onUp);
      };
      document.addEventListener("pointermove", onMove);
      document.addEventListener("pointerup", onUp);
    },
    [seekTo],
  );

  function onTrackKeyDown(e: React.KeyboardEvent) {
    const audio = audioRef.current;
    if (!audio) return;
    const step = 5 / (audio.duration || 1);
    switch (e.key) {
      case "ArrowRight":
        e.preventDefault();
        seekTo(progress + step);
        break;
      case "ArrowLeft":
        e.preventDefault();
        seekTo(progress - step);
        break;
      case "Home":
        e.preventDefault();
        seekTo(0);
        break;
      case "End":
        e.preventDefault();
        seekTo(1);
        break;
      case " ":
      case "Enter":
        e.preventDefault();
        toggle();
        break;
    }
  }

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: PointerEvent) => {
      if (!(e.target as HTMLElement).closest("[data-player-menu]")) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [menuOpen]);

  return (
    <div className="mt-3.5 flex items-center gap-4 rounded-full border border-[var(--line-strong)] bg-gradient-to-b from-[var(--surface-raised)] to-[var(--surface-inset)] px-3 py-2.5">
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={onError}
      />

      <button
        type="button"
        onClick={toggle}
        aria-label={playing ? "Pause" : "Play"}
        className="grid h-11 w-11 shrink-0 place-items-center rounded-full border-2 transition-colors hover:bg-[var(--treatment)]/10"
        style={{ borderColor: "var(--treatment)", color: "var(--treatment)" }}
      >
        {playing ? (
          <PauseIcon size={17} />
        ) : (
          // Nudged right so the triangle looks centred in the circle.
          <PlayIcon size={17} className="translate-x-[1px]" />
        )}
      </button>

      <span className="shrink-0 font-mono text-[13px] tnum">
        <span className="text-[var(--ink)]">{clock(current)}</span>
        <span className="text-[var(--ink-4)]"> / </span>
        <span className="text-[var(--ink-3)]">{clock(duration)}</span>
      </span>

      <div
        ref={trackRef}
        role="slider"
        tabIndex={0}
        aria-label="Seek"
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(current)}
        aria-valuetext={`${clock(current)} of ${clock(duration)}`}
        onPointerDown={startScrub}
        onKeyDown={onTrackKeyDown}
        // Generous hit area around a 4px bar.
        className="group relative min-w-0 flex-1 cursor-pointer py-3 focus:outline-none"
      >
        <div className="h-1 rounded-full bg-[var(--line-strong)]">
          <div
            className="h-1 rounded-full"
            style={{
              width: `${progress * 100}%`,
              background: "var(--treatment)",
            }}
          />
        </div>
        <span
          className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full shadow-[0_0_0_3px_var(--surface-inset)] transition-transform group-hover:scale-125 group-focus:scale-125"
          style={{ left: `${progress * 100}%`, background: "var(--treatment)" }}
        />
      </div>

      <button
        type="button"
        onClick={() => {
          const audio = audioRef.current;
          if (!audio) return;
          audio.muted = !audio.muted;
          setMuted(audio.muted);
        }}
        aria-label={muted ? "Unmute" : "Mute"}
        aria-pressed={muted}
        className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[var(--surface-inset)] text-[var(--ink-2)] transition-colors hover:text-[var(--ink)]"
      >
        <VolumeIcon size={17} muted={muted} />
      </button>

      <div className="relative shrink-0" data-player-menu>
        <button
          type="button"
          onClick={() => setMenuOpen((o) => !o)}
          aria-label="Playback options"
          aria-expanded={menuOpen}
          className="grid h-9 w-9 place-items-center rounded-full border border-[var(--line-strong)] text-[var(--ink-3)] transition-colors hover:text-[var(--ink)]"
        >
          <DotsIcon size={16} />
        </button>

        {menuOpen && (
          <div className="absolute right-0 bottom-11 z-20 w-36 rounded-lg border border-[var(--line-strong)] bg-[var(--surface-raised)] p-1 shadow-2xl shadow-black/60">
            <div className="px-2.5 pt-1 pb-1.5 font-mono text-[9.5px] uppercase tracking-[0.16em] text-[var(--ink-4)]">
              Speed
            </div>
            {SPEEDS.map((rate) => (
              <button
                key={rate}
                type="button"
                onClick={() => {
                  const audio = audioRef.current;
                  if (audio) audio.playbackRate = rate;
                  setSpeed(rate);
                  setMenuOpen(false);
                }}
                className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left font-mono text-[12.5px] hover:bg-[var(--surface-inset)]"
              >
                <span
                  className="w-3 shrink-0"
                  style={{ color: speed === rate ? "var(--treatment)" : "transparent" }}
                >
                  ✓
                </span>
                <span
                  className={
                    speed === rate ? "text-[var(--ink)]" : "text-[var(--ink-2)]"
                  }
                >
                  {rate}×
                </span>
              </button>
            ))}
            <a
              href={src}
              target="_blank"
              rel="noreferrer"
              className="mt-1 block border-t border-[var(--line)] px-2.5 pt-2 pb-1 font-mono text-[12px] text-[var(--ink-3)] hover:text-[var(--ink)]"
            >
              Open the file
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
