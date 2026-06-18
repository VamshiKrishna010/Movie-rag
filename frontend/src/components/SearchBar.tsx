interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  inline?: boolean;
}

function SearchIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="currentColor"
      className="h-3.5 w-3.5 shrink-0 text-muted"
      aria-hidden
    >
      <path
        fillRule="evenodd"
        d="M10.5 3.75a6.75 6.75 0 100 13.5 6.75 6.75 0 000-13.5zM2.25 10.5a8.25 8.25 0 1114.59 5.28l4.69 4.69a.75.75 0 11-1.06 1.06l-4.69-4.69A8.25 8.25 0 012.25 10.5z"
        clipRule="evenodd"
      />
    </svg>
  );
}

export function SearchBar({
  value,
  onChange,
  onSubmit,
  inline = false,
}: SearchBarProps) {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit();
  };

  if (inline) {
    return (
      <form onSubmit={handleSubmit} className="w-full min-w-0 flex-1 md:max-w-[11rem] lg:max-w-[13rem]">
        <div className="flex items-center gap-1.5 rounded-full border border-border bg-bg/60 px-2.5 py-1">
          <SearchIcon />
          <input
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="Search..."
            className="min-w-0 flex-1 bg-transparent text-xs text-text outline-none placeholder:text-muted"
          />
        </div>
      </form>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="mx-auto flex w-full max-w-xl">
      <div className="flex w-full items-center gap-2 rounded-full border border-border bg-bg/60 px-4 py-2.5">
        <SearchIcon />
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Search movies..."
          className="min-w-0 flex-1 bg-transparent text-sm text-text outline-none placeholder:text-muted"
        />
      </div>
    </form>
  );
}
