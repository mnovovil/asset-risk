import { useId, useState, type DragEvent } from "react";

interface DropZoneProps {
  onFile: (file: File) => void;
}

export function DropZone({ onFile }: DropZoneProps) {
  const inputId = useId();
  const [dragging, setDragging] = useState(false);

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) onFile(file);
  }

  return (
    <div
      className={dragging ? "dropzone dropzone-active" : "dropzone"}
      data-testid="dropzone"
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
    >
      <p className="dropzone-title">Drop your portfolio CSV here</p>
      <p className="muted">
        It needs the columns <code>id</code>, <code>lat</code> and <code>lon</code>.
      </p>
      <label className="button" htmlFor={inputId}>
        Choose a file
      </label>
      <input
        id={inputId}
        className="visually-hidden"
        type="file"
        accept=".csv,text/csv"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onFile(file);
          event.target.value = "";
        }}
      />
    </div>
  );
}
