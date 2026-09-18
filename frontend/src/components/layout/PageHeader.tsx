import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export function PageHeader({
  icon: Icon,
  title,
  description,
  actions,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/12 text-primary ring-1 ring-inset ring-primary/20">
          <Icon className="h-4.5 w-4.5" />
        </span>
        <div>
          <h1 className="text-lg font-bold tracking-tight">{title}</h1>
          <p className="mt-0.5 max-w-2xl text-xs leading-relaxed text-muted-foreground">
            {description}
          </p>
        </div>
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}
