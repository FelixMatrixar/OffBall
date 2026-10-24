/** Numbered steps joined by lines that fill as each step is completed. */
export function Stepper({ steps, current }: { steps: readonly string[]; current: number }) {
  return (
    <ol className="stepper" aria-label="Progress">
      {steps.map((label, i) => {
        const state = i < current ? 'done' : i === current ? 'current' : 'todo';
        return (
          <li key={label}>
            <span className="step-dot" data-state={state} aria-current={state === 'current' ? 'step' : undefined}>
              {i + 1}
            </span>
            <span className="step-label" data-active={state !== 'todo'}>
              {label}
            </span>
            {i < steps.length - 1 && (
              <span className="step-line" aria-hidden="true">
                <span className="step-line-fill" data-done={i < current} />
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
