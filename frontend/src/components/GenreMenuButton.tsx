interface GenreMenuButtonProps {
  onClick: () => void;
}

export function GenreMenuButton({ onClick }: GenreMenuButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Open genre menu"
      className="flex h-8 w-8 shrink-0 flex-col items-center justify-center gap-[3px] rounded-full text-muted transition-colors hover:bg-bg hover:text-text"
    >
      <span className="block h-0.5 w-3.5 rounded-full bg-current" />
      <span className="block h-0.5 w-3.5 rounded-full bg-current" />
      <span className="block h-0.5 w-3.5 rounded-full bg-current" />
    </button>
  );
}
