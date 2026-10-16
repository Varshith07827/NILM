/**
 * Keeps the 3-D scene's floating labels from piling on top of each other.
 *
 * Every label in the scene carries `data-label-priority`. A few times a second
 * this measures where each one actually landed on screen, keeps them in order
 * of priority, and fades out any that would overlap a label already kept.
 * Measuring the real DOM boxes, rather than predicting them from 3-D
 * positions, means it stays right as the camera orbits and zooms and as label
 * text changes length.
 *
 * Visibility is set as a data attribute rather than React state, so a
 * decluttering pass never re-renders the scene.
 */

import { useEffect, type RefObject } from "react";

const INTERVAL_MS = 200;
/** Extra breathing room around each label, in pixels. */
const MARGIN_PX = 3;

interface Box {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

function overlaps(a: Box, b: Box): boolean {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

export function useLabelDeclutter(container: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const pass = () => {
      const root = container.current;
      if (!root) return;
      const labels = Array.from(root.querySelectorAll<HTMLElement>("[data-label-priority]"));
      const measured = labels
        .map((element) => {
          const rect = element.getBoundingClientRect();
          return {
            element,
            priority: Number(element.dataset.labelPriority) || 0,
            box: {
              left: rect.left - MARGIN_PX,
              right: rect.right + MARGIN_PX,
              top: rect.top - MARGIN_PX,
              bottom: rect.bottom + MARGIN_PX,
            },
            empty: rect.width === 0 || rect.height === 0,
          };
        })
        .sort((a, b) => b.priority - a.priority);

      const kept: Box[] = [];
      for (const label of measured) {
        const hide = !label.empty && kept.some((box) => overlaps(box, label.box));
        if (!hide && !label.empty) kept.push(label.box);
        const value = hide ? "true" : "false";
        if (label.element.dataset.labelHidden !== value) {
          label.element.dataset.labelHidden = value;
        }
      }
    };

    const timer = window.setInterval(pass, INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [container]);
}

/** Priority of a device's label: what the viewer is looking at comes first. */
export function deviceLabelPriority(options: {
  selected: boolean;
  hovered: boolean;
  error: boolean;
  watts: number;
}): number {
  if (options.selected) return 100;
  if (options.hovered) return 95;
  if (options.error) return 50;
  // Bigger loads first: 10 for a phone charger up to ~45 for an AC or hob.
  return 10 + Math.min(35, Math.sqrt(Math.max(options.watts, 0)) * 0.8);
}
