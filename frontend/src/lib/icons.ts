/**
 * Appliance icon registry.
 *
 * Explicit rather than `import * as Icons from "lucide-react"`. The wildcard
 * form is convenient but defeats tree-shaking: it pulls the entire icon set
 * (well over a thousand components) into the bundle to use twelve of them.
 * Naming them costs one line each and keeps the build small.
 */

import {
  AirVent,
  Blend,
  CookingPot,
  Fan,
  Lamp,
  Laptop,
  Lightbulb,
  Microwave,
  Plug,
  Refrigerator,
  Smartphone,
  Tv,
  WashingMachine,
  type LucideIcon,
} from "lucide-react";

const REGISTRY: Record<string, LucideIcon> = {
  AirVent,
  Blend,
  CookingPot,
  Fan,
  Lamp,
  Laptop,
  Lightbulb,
  Microwave,
  Plug,
  Refrigerator,
  Smartphone,
  Tv,
  WashingMachine,
};

/** Look up an appliance icon by the name the backend supplies. */
export function applianceIcon(name: string): LucideIcon {
  return REGISTRY[name] ?? Plug;
}
