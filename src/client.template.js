/* eslint-disable */
/**
 * 大肥鱼桌宠 · Client half.
 *
 * Registered into `conversation.input.overlay`, which the resident composer
 * renders inside the input card, so the mascot hangs off the card's top edge
 * at its right end.
 *
 * Seven states own a pool of stickers and pick one at random (then rotate to
 * another after a while); `idle` is scripted instead: a random opening sticker,
 * then a fixed sequence, ending locked on the charging sticker.
 *
 * Nothing here reads session events: the framework standard props already
 * carry the lifecycle snapshot, the pending-interaction status and the
 * context-pressure projection.
 */
window.__ModuleLoader__.load({
  id: 'dsh-fatfish',
  factory(require) {
    const React = require('react');
    const h = React.createElement;
    const { useEffect, useRef, useState } = React;

    /** { pools: { state: [{id,label,src,ms,count,loops}] }, idle: {...} } */
    const DATA = /*__FRAMES__*/;
    const CFG = {
      idleMs: 180000,
      doneMs: 6000,
      errorMs: 8000,
      stuffedRatio: 0.85,
      tickMs: 500,
      // 同一状态停留超过这个时长就换个同状态表情（±25% 抖动，避免整齐划一）
      rotateMs: 45000,
      // 宠物贴住输入卡片上沿；正文区靠这条占位带整体上移，最后一行不会压在宠物下面
      petSize: 96,
      bandGap: 6,
    };
    const CSS = [
      '.dsh-fatfish{position:absolute;top:0;right:40px;width:96px;height:96px;',
      'transform:translateY(calc(-100% + 2px));pointer-events:none;user-select:none;',
      'z-index:0;filter:drop-shadow(0 8px 14px rgba(20,24,60,.18));}',
      '.dsh-fatfish img{width:100%;height:100%;display:block;object-fit:contain;',
      '-webkit-user-drag:none;}',
      '.dsh-fatfish-band{height:' + (CFG.petSize + CFG.bandGap) + 'px;pointer-events:none;}',
    ].join('');

    /** Pick a sticker from a pool, avoiding the previous one. */
    function pickFrom(pool, previousId) {
      if (!pool || pool.length === 0) return null;
      if (pool.length === 1) return pool[0];
      const others = previousId === undefined ? pool : pool.filter(s => s.id !== previousId);
      const from = others.length > 0 ? others : pool;
      return from[Math.floor(Math.random() * from.length)];
    }

    /** Absent-framework fallbacks keep the entry renderable outside a session. */
    const EMPTY_SESSION = {
      running: false, promptError: null, lastAgentError: null, openError: null,
    };

    /**
     * Invisible spacer above the composer card. It rides the in-flow dock slot
     * so the scroll body ends above the mascot's box: the pet keeps hugging the
     * card's top edge, and no message line can stop underneath it.
     */
    function Band() {
      return h('div', { className: 'dsh-fatfish-band', 'aria-hidden': 'true' },
        h('style', null, CSS));
    }

    function Mascot(props) {
      const sessionId = props.sessionId;
      // The standard kit is normally present; the fallbacks keep this entry
      // from crashing (and blanking the slot) if a shell ships without it.
      const useSession = typeof props.useSession === 'function'
        ? props.useSession
        : (selector) => selector(EMPTY_SESSION);
      const useSessionStatus = typeof props.useSessionStatus === 'function'
        ? props.useSessionStatus
        : () => undefined;
      const useProjection = typeof props.useProjection === 'function'
        ? props.useProjection
        : () => undefined;

      const running = useSession(s => s.running);
      const promptError = useSession(s => s.promptError);
      const agentError = useSession(s => s.lastAgentError);
      const openError = useSession(s => s.openError);
      // Narrow selectors: the mascot re-renders only when a decision input flips.
      const pendingKind = useSessionStatus((map) => {
        const status = sessionId === undefined ? undefined : map.get(sessionId);
        const interaction = status && status.pendingInteraction;
        return interaction ? String(interaction.kind) : '';
      });
      const stuffed = useProjection('contextPressure', (pressure) => {
        if (!pressure) return false;
        const used = pressure.projectedTokens !== undefined ? pressure.projectedTokens : pressure.pressureTokens;
        return used !== undefined && pressure.contextWindow !== undefined && pressure.contextWindow > 0
          && used / pressure.contextWindow >= CFG.stuffedRatio;
      });

      const initial = pickFrom(DATA.pools.waiting, undefined);
      const [view, setView] = useState(() => ({
        state: 'waiting', id: initial.id, src: initial.src, nonce: 0,
      }));

      const viewRef = useRef(view);
      const shownAt = useRef(Date.now());
      const rotateIn = useRef(CFG.rotateMs);
      const nonce = useRef(0);
      const live = useRef({
        running: false, focused: false, lastInput: Date.now(),
        doneAt: 0, errorAt: 0, errorKey: '', stuffed: false, pendingKind: '',
      });
      /** null while not idle; { index, startedAt, until } once the script runs. */
      const idleScript = useRef(null);

      live.current.running = running === true;

      const errorKey = promptError ? 'prompt:' + JSON.stringify(promptError) : '';
      const agentKey = agentError ? 'agent:' + String(agentError) : '';
      const openKey = openError ? 'open:' + String(openError) : '';
      const errKey = errorKey || agentKey || openKey;
      if (errKey !== live.current.errorKey) {
        live.current.errorKey = errKey;
        live.current.errorAt = errKey === '' ? 0 : Date.now();
      }

      live.current.pendingKind = pendingKind || '';
      live.current.stuffed = stuffed === true;

      const prevRunning = useRef(running === true);
      if (prevRunning.current !== (running === true)) {
        prevRunning.current = running === true;
        if (!prevRunning.current) live.current.doneAt = Date.now();
      }

      const decide = () => {
        const now = Date.now();
        const s = live.current;
        if (s.errorKey !== '' && now - s.errorAt < CFG.errorMs) return 'error';
        if (s.pendingKind === 'approval') return 'approval';
        if (s.pendingKind === 'question') return 'question';
        if (s.running) return 'running';
        if (now - s.doneAt < CFG.doneMs) return 'done';
        if (!s.focused && s.stuffed) return 'stuffed';
        if (s.focused) return 'typing';
        if (now - s.lastInput >= CFG.idleMs) return 'idle';
        return 'waiting';
      };

      /** Render one exact sticker; the key bump restarts its animation. */
      const applySticker = (stateName, sticker) => {
        nonce.current += 1;
        viewRef.current = { state: stateName, id: sticker.id, src: sticker.src, nonce: nonce.current };
        shownAt.current = Date.now();
        rotateIn.current = CFG.rotateMs * (0.75 + Math.random() * 0.5);
        setView(viewRef.current);
      };

      const showPoolState = (name) => {
        const next = pickFrom(DATA.pools[name], viewRef.current.id);
        if (next) applySticker(name, next);
      };

      /** Advance the idle script; returns after applying whatever sticker it wants. */
      const runIdle = () => {
        const idle = DATA.idle;
        const now = Date.now();
        const current = idleScript.current;
        if (current === null) {
          const opening = pickFrom(idle.opening, undefined);
          idleScript.current = { index: -1, startedAt: now, until: 0 };
          applySticker('idle', opening);
          return;
        }
        const startStep = (index) => {
          const step = idle.sequence[index];
          const until = step.loops > 0 ? now + step.count * step.ms * step.loops : Infinity;
          idleScript.current = { index, startedAt: now, until };
          applySticker('idle', step);
        };
        if (current.index === -1) {
          if (now - current.startedAt >= idle.afterMs) startStep(0);
          return;
        }
        if (current.until !== Infinity && now >= current.until && current.index + 1 < idle.sequence.length) {
          startStep(current.index + 1);
        }
      };

      useEffect(() => {
        const tick = () => {
          if (document.hidden) return;
          const name = decide();
          if (name === 'idle') {
            runIdle();
            return;
          }
          idleScript.current = null;
          if (name !== viewRef.current.state) {
            showPoolState(name);
          } else if (Date.now() - shownAt.current >= rotateIn.current) {
            const pool = DATA.pools[name];
            if (pool && pool.length > 1) {
              const next = pickFrom(pool, viewRef.current.id);
              if (next) applySticker(name, next);
            }
          }
        };
        const timer = setInterval(tick, CFG.tickMs);
        tick();
        return () => { clearInterval(timer); };
      });

      useEffect(() => {
        const bump = () => { live.current.lastInput = Date.now(); };
        const onFocusIn = (event) => {
          const target = event.target;
          if (target && target.closest && target.closest('[data-composer-card]')) {
            live.current.focused = true;
            bump();
          }
        };
        const onFocusOut = (event) => {
          const target = event.target;
          if (target && target.closest && target.closest('[data-composer-card]')) {
            live.current.focused = false;
            bump();
          }
        };
        document.addEventListener('pointerdown', bump, true);
        document.addEventListener('keydown', bump, true);
        document.addEventListener('focusin', onFocusIn, true);
        document.addEventListener('focusout', onFocusOut, true);
        return () => {
          document.removeEventListener('pointerdown', bump, true);
          document.removeEventListener('keydown', bump, true);
          document.removeEventListener('focusin', onFocusIn, true);
          document.removeEventListener('focusout', onFocusOut, true);
        };
      }, []);

      return h('div', { className: 'dsh-fatfish', 'aria-hidden': 'true', 'data-state': view.state },
        h('style', null, CSS),
        h('img', { key: view.nonce, src: view.src, alt: '', draggable: false }),
      );
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('conversation.input.dock', () => ctx.slots.register({
          name: 'conversation.input.dock',
          id: 'fatfish-band',
          order: 10,
        }, Band));
        ctx.slots.inject('conversation.input.overlay', () => ctx.slots.register({
          name: 'conversation.input.overlay',
          id: 'fatfish-mascot',
          order: 60,
        }, Mascot));
      },
    };
  },
});
