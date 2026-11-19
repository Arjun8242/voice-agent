/**
 * use:reveal fades a block in the first time it scrolls into view (the landing page's sections).
 * One shared observer serves every block; a block is forgotten once shown, so nothing runs after.
 * Without IntersectionObserver (or with reduced motion, see app.css) the block simply shows.
 */

let observer: IntersectionObserver | null = null;

function shared(): IntersectionObserver {
  observer ??= new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add('in');
        observer?.unobserve(entry.target);
      }
    },
    { threshold: 0.15 },
  );
  return observer;
}

export function reveal(node: HTMLElement): { destroy: () => void } {
  node.classList.add('reveal');
  if (typeof IntersectionObserver === 'undefined') {
    node.classList.add('in');
    return { destroy: () => {} };
  }
  shared().observe(node);
  return { destroy: () => observer?.unobserve(node) };
}
