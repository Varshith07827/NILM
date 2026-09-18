import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[0.7rem] font-medium transition-colors [&_svg]:size-3",
  {
    variants: {
      variant: {
        default: "border-primary/25 bg-primary/12 text-primary",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-border text-muted-foreground",
        success: "border-success/25 bg-success/12 text-success",
        warning: "border-warning/25 bg-warning/12 text-warning",
        destructive: "border-destructive/25 bg-destructive/12 text-destructive",
        accent: "border-accent/25 bg-accent/12 text-accent",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
