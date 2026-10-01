import { useQuery } from "@tanstack/react-query";
import { KeyRound, Moon, Sun } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { apiBaseUrl, fetchReady, getApiKey, setApiKey } from "@/lib/api";
import type { Theme } from "@/lib/theme";
import { cn } from "@/lib/utils";

interface Props {
  version?: string;
  theme: Theme;
  onToggleTheme: () => void;
  apiKeyRequired: boolean;
  onApiKeyChange: () => void;
}

export function Header({ version, theme, onToggleTheme, apiKeyRequired, onApiKeyChange }: Props) {
  const ready = useQuery({ queryKey: ["ready"], queryFn: fetchReady, refetchInterval: 15_000 });
  const [editingKey, setEditingKey] = useState(false);
  const [key, setKey] = useState(getApiKey);

  return (
    <header className="sticky top-0 z-20 border-b bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-3 px-4">
        <img src="./logo.svg" alt="" className="size-8" />
        <div className="flex items-baseline gap-2">
          <span className="text-lg font-semibold tracking-tight">Docling Serve</span>
          {version && <span className="font-mono text-xs text-muted-foreground">v{version}</span>}
        </div>

        <Tooltip>
          <TooltipTrigger asChild>
            <span
              className={cn(
                "ml-1 size-2.5 rounded-full",
                ready.data === undefined ? "bg-muted-foreground" : ready.data ? "bg-success" : "bg-destructive",
              )}
              aria-label={ready.data ? "Server ready" : "Server not ready"}
            />
          </TooltipTrigger>
          <TooltipContent>
            {ready.data ? "Ready" : "Not ready"} · {apiBaseUrl()}
          </TooltipContent>
        </Tooltip>

        <div className="ml-auto flex items-center gap-2">
          {(apiKeyRequired || getApiKey()) &&
            (editingKey ? (
              <form
                className="flex items-center gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  setApiKey(key.trim());
                  setEditingKey(false);
                  onApiKeyChange();
                }}
              >
                <Input
                  type="password"
                  autoFocus
                  placeholder="API key"
                  className="h-8 w-56"
                  value={key}
                  onChange={(event) => setKey(event.target.value)}
                />
                <Button size="sm" type="submit">
                  Save
                </Button>
              </form>
            ) : (
              <Button variant={getApiKey() ? "outline" : "default"} size="sm" onClick={() => setEditingKey(true)}>
                <KeyRound className="size-4" />
                {getApiKey() ? "API key set" : "Set API key"}
              </Button>
            ))}
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggleTheme}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </Button>
        </div>
      </div>
    </header>
  );
}
