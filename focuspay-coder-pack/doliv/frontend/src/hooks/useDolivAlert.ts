import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';

const POLL_MS = 5000;

/** Poll notifications and invalidate doliv requests when new doliv_request arrives. */
export function useDolivPolling() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const lastNotifIds = useRef<Set<number>>(new Set());
  const initialized = useRef(false);

  useEffect(() => {
    if (user?.role !== 'dolivshchik') return;

    const poll = async () => {
      try {
        const notifs = await api.notifications({ unread_only: true, limit: 10 });
        const dolivNotifs = notifs.filter((n) => n.kind === 'doliv_request');
        const currentIds = new Set(dolivNotifs.map((n) => n.id));

        if (initialized.current) {
          const hasNew = dolivNotifs.some((n) => !lastNotifIds.current.has(n.id));
          if (hasNew) {
            qc.invalidateQueries({ queryKey: ['doliv-requests'] });
            qc.invalidateQueries({ queryKey: ['doliv-stats'] });
          }
        } else {
          initialized.current = true;
        }
        lastNotifIds.current = currentIds;
      } catch {
        // ignore polling errors
      }
    };

    poll();
    const id = window.setInterval(poll, POLL_MS);
    return () => window.clearInterval(id);
  }, [user?.role, qc]);
}

function playBeep() {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = 880;
    gain.gain.value = 0.3;
    osc.start();
    osc.stop(ctx.currentTime + 0.25);
    osc.onended = () => ctx.close();
  } catch {
    // autoplay may be blocked until user interaction
  }
}

export function isDolivSoundEnabled(): boolean {
  return localStorage.getItem('doliv_sound_enabled') !== 'false';
}

export function setDolivSoundEnabled(enabled: boolean) {
  localStorage.setItem('doliv_sound_enabled', enabled ? 'true' : 'false');
}

/** Play sound when new pending doliv requests appear. */
export function useDolivAlert(pendingIds: number[]) {
  const { user } = useAuth();
  const seenIds = useRef<Set<number>>(new Set());
  const initialized = useRef(false);

  useEffect(() => {
    if (user?.role !== 'dolivshchik') return;

    const current = new Set(pendingIds);
    if (!initialized.current) {
      seenIds.current = current;
      initialized.current = true;
      return;
    }

    const hasNew = pendingIds.some((id) => !seenIds.current.has(id));
    if (hasNew && isDolivSoundEnabled()) {
      playBeep();
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        new Notification('Новая заявка на долив', { body: 'Появился новый реквизит для долива' });
      }
    }
    seenIds.current = current;
  }, [pendingIds, user?.role]);
}
