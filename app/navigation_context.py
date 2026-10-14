"""Browser-local scroll context for the public workflow pages.

This component reads and changes only its owning browser scroll container.
Scrolling never sends a Streamlit state update or calculation event.
"""

from __future__ import annotations

import json
import secrets

import streamlit as st

from app.workflow_navigation import BY_KEY

SESSION_KEY = "_navigation_context_session"

_JS = """
export default function ({data, parentElement}) {
  if (!data || !parentElement) return;
  const registryKey = Symbol.for("sector.navigation.scroll.v1");
  const registry = window[registryKey] || (window[registryKey] = new Map());
  let memory = registry.get(data.scope);
  if (!memory || memory.epoch !== data.epoch) {
    if (memory?.active) memory.active.dispose();
    memory = {epoch: data.epoch, positions: new Map(), active: null};
    registry.set(data.scope, memory);
  }
  while (registry.size > 4) {
    const oldest = registry.keys().next().value;
    registry.get(oldest)?.active?.dispose();
    registry.delete(oldest);
  }

  function composedParent(node) {
    if (!node) return null;
    return node.parentElement || node.host || node.getRootNode?.().host || null;
  }
  function scrollOwner(node) {
    for (let item = node; item; item = composedParent(item)) {
      if (item.nodeType !== 1) continue;
      const overflow = window.getComputedStyle(item).overflowY;
      // The zero-height component itself has an overflow:auto wrapper.
      // It cannot be the visible page's scrolling viewport.
      if ((overflow === "auto" || overflow === "scroll") && item.clientHeight > 0) return item;
    }
    return document.scrollingElement;
  }
  const owner = scrollOwner(parentElement);
  if (!owner) return;
  const key = data.context;
  const existing = memory.positions.get(key);
  const target = existing || {x: 0, y: 0};
  const previous = memory.active;
  if (previous) previous.dispose();
  let disposed = false;
  let restoring = data.restore !== false;
  let navigationPending = false;
  let frame = 0;
  let timer = 0;
  let observer = null;

  function remember() {
    if (disposed || restoring || navigationPending) return;
    memory.positions.delete(key);
    memory.positions.set(key, {x: owner.scrollLeft, y: owner.scrollTop});
    while (memory.positions.size > 64) {
      memory.positions.delete(memory.positions.keys().next().value);
    }
  }
  function onScroll() { remember(); }
  function finishRestore() {
    restoring = false;
    if (observer) observer.disconnect();
    clearTimeout(timer);
    cancelAnimationFrame(frame);
    // Keep a remembered position if content has not reached its final height.
    // The next visit can restore it after a complete render.
  }
  function restore() {
    if (disposed || !restoring) return;
    owner.scrollTo({left: target.x, top: target.y, behavior: "instant"});
    if (owner.scrollHeight - owner.clientHeight >= target.y) finishRestore();
  }
  function onIntent() {
    if (disposed) return;
    finishRestore();
    navigationPending = false;
  }
  function onKey(event) {
    if (["PageDown", "PageUp", "Home", "End", "ArrowDown", "ArrowUp", " "].includes(event.key)) {
      onIntent();
    }
  }
  function onNavigation(event) {
    const path = event.composedPath ? event.composedPath() : [event.target];
    const control = path.find(node => node?.matches?.(
      "a,button,select,[role='tab'],[role='radio'],[role='option'],input[type='radio']"
    ));
    if (!control) return;
    remember();
    // Native navigation can reset scroll before the old component unmounts.
    // Preserve the position recorded before that transition.
    navigationPending = true;
  }
  function onHistory() { remember(); navigationPending = true; }
  function dispose() {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    clearTimeout(timer);
    if (observer) observer.disconnect();
    owner.removeEventListener("scroll", onScroll);
    owner.removeEventListener("wheel", onIntent);
    owner.removeEventListener("touchmove", onIntent);
    owner.removeEventListener("pointerdown", onIntent);
    document.removeEventListener("keydown", onKey, true);
    document.removeEventListener("click", onNavigation, true);
    window.removeEventListener("popstate", onHistory);
    if (memory.active?.dispose === dispose) memory.active = null;
  }
  memory.active = {key, dispose};
  owner.addEventListener("scroll", onScroll, {passive: true});
  owner.addEventListener("wheel", onIntent, {passive: true});
  owner.addEventListener("touchmove", onIntent, {passive: true});
  owner.addEventListener("pointerdown", onIntent, {passive: true});
  document.addEventListener("keydown", onKey, true);
  document.addEventListener("click", onNavigation, true);
  window.addEventListener("popstate", onHistory);
  if (data.restore === false) {
    // Correction panels precede the page controls. Explicit issue navigation
    // must reveal that panel even when this page was previously scrolled down.
    owner.scrollTo({left: 0, top: 0, behavior: "instant"});
  }
  if (restoring) {
    observer = new ResizeObserver(() => { frame = requestAnimationFrame(restore); });
    observer.observe(owner);
    for (const child of owner.children) observer.observe(child);
    frame = requestAnimationFrame(restore);
    timer = setTimeout(finishRestore, 1200);
  }
  return dispose;
}
"""

def _scroll_context(**kwargs):
    """Register the fixed definition in the active runtime before mounting.

    Streamlit can replace its runtime while this Python module stays imported.
    Its public registration API accepts the same immutable definition again.
    Keeping registration beside the mount therefore avoids a callable bound
    to a definition held only by an earlier runtime.
    """
    component = st.components.v2.component(
        "sector_navigation_scroll_context",
        html='<span aria-hidden="true"></span>',
        js=_JS,
    )
    return component(**kwargs)


def context_data(page: str, subpage: str, project_epoch: int, scope: str,
                 *, restore: bool = True) -> dict:
    """Build bounded presentation data without reading engineering state."""
    if page not in BY_KEY:
        raise ValueError("Unknown workflow page")
    if not isinstance(subpage, str) or len(subpage) > 160:
        raise ValueError("Subpage context must contain at most 160 characters")
    if type(project_epoch) is not int or project_epoch < 0:
        raise ValueError("Project epoch must be a nonnegative integer")
    if not isinstance(scope, str) or not 1 <= len(scope) <= 64:
        raise ValueError("Scroll session scope is invalid")
    if type(restore) is not bool:
        raise ValueError("Restore preference must be Boolean")
    return {
        "scope": scope,
        "epoch": project_epoch,
        "context": json.dumps([page, subpage], ensure_ascii=True),
        "restore": restore,
    }


def render(page: str, subpage: str = "", *, project_epoch: int,
           restore: bool = True) -> None:
    """Mount once in the active workspace after its page content.

    The caller supplies a project epoch that advances on each replacement.
    Pass ``restore=False`` for an explicit correction-focus transition so the
    correction target takes priority over the remembered page position.
    """
    scope = st.session_state.get(SESSION_KEY)
    if not isinstance(scope, str) or not 1 <= len(scope) <= 64:
        scope = secrets.token_hex(16)
        st.session_state[SESSION_KEY] = scope
    _scroll_context(
        data=context_data(page, subpage, project_epoch, scope, restore=restore),
        key="_navigation_scroll_context", height=0, width="stretch",
    )
