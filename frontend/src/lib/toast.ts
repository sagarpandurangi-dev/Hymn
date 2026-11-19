/** Tiny app-wide toast bus. `ToastHost` (mounted in the root layout) listens. */
type Listener = (message: string) => void;

const listeners = new Set<Listener>();

export function showToast(message: string): void {
  listeners.forEach((l) => l(message));
}

export function subscribeToast(listener: Listener): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
