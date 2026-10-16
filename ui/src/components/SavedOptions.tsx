import { Bookmark, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { OptionValues } from "@/lib/options";

const STORAGE_KEY = "docling-serve-ui:saved-options";

type Saved = Record<string, OptionValues>;

function load(): Saved {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Saved;
  } catch {
    return {};
  }
}

function store(saved: Saved) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
  } catch {
    // Not persisted; the list lasts for this page load.
  }
}

/** Named option sets, kept in this browser only. */
export function SavedOptions({
  values,
  onLoad,
}: {
  values: OptionValues;
  onLoad: (values: OptionValues) => void;
}) {
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState<Saved>(load);
  const [name, setName] = useState("");

  const update = (next: Saved) => {
    setSaved(next);
    store(next);
  };

  return (
    <div className="relative">
      <Button variant="ghost" size="sm" onClick={() => setOpen((current) => !current)} aria-expanded={open}>
        <Bookmark className="size-3.5" /> Saved
      </Button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-64 space-y-2 rounded-md border bg-popover p-3 text-popover-foreground shadow-md">
          <form
            className="flex gap-1.5"
            onSubmit={(event) => {
              event.preventDefault();
              if (!name.trim()) return;
              update({ ...saved, [name.trim()]: values });
              setName("");
            }}
          >
            <Input
              className="h-8"
              placeholder="Name these options"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            <Button size="sm" type="submit" disabled={!name.trim()}>
              Save
            </Button>
          </form>
          {Object.keys(saved).length === 0 ? (
            <p className="text-xs text-muted-foreground">No saved options yet.</p>
          ) : (
            <ul className="space-y-0.5">
              {Object.keys(saved).map((key) => (
                <li key={key} className="flex items-center gap-1">
                  <button
                    type="button"
                    className="flex-1 truncate rounded px-2 py-1 text-left text-sm hover:bg-muted"
                    onClick={() => {
                      onLoad(saved[key]);
                      setOpen(false);
                    }}
                  >
                    {key}
                  </button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    aria-label={`Delete ${key}`}
                    onClick={() => {
                      const { [key]: _removed, ...rest } = saved;
                      update(rest);
                    }}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
