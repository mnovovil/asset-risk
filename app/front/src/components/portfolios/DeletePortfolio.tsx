import { useId, useRef, useState } from "react";

import { ApiError, deleteRun, type RunStatus } from "@/api/client";

interface DeletePortfolioProps {
  run: RunStatus;
  name: string;
  /** Called once the server has deleted the run. */
  onDeleted: (run: RunStatus) => void;
}

/**
 * A Delete button that asks first, in a native modal dialog: it keeps focus inside, closes on
 * Escape and gives focus back to the button. Queued and running runs can't be deleted, so they
 * get no button.
 */
export function DeletePortfolio({ run, name, onDeleted }: DeletePortfolioProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleId = useId();

  if (run.status === "queued" || run.status === "running") return null;

  function open() {
    setError(null);
    dialog.current?.showModal();
  }

  async function confirm() {
    setDeleting(true);
    setError(null);
    try {
      await deleteRun(run.run_id);
      dialog.current?.close();
      onDeleted(run);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The portfolio couldn't be deleted.");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      <button type="button" className="card-delete" onClick={open} aria-label={`Delete ${name}`}>
        Delete
      </button>
      <dialog ref={dialog} className="confirm-dialog" aria-labelledby={titleId}>
        <h2 id={titleId}>Delete {name}?</h2>
        <p>Its results are removed for good. This can't be undone.</p>
        {error && (
          <p className="notice notice-error" role="alert">
            {error}
          </p>
        )}
        <div className="confirm-actions">
          <button
            type="button"
            className="button"
            onClick={() => dialog.current?.close()}
            disabled={deleting}
            autoFocus
          >
            Cancel
          </button>
          <button
            type="button"
            className="button button-danger"
            onClick={() => void confirm()}
            disabled={deleting}
          >
            {deleting ? "Deleting…" : "Delete"}
          </button>
        </div>
      </dialog>
    </>
  );
}
