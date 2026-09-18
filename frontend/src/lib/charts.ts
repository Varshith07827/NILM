/**
 * Chart.js registration and shared styling.
 *
 * Registered once here rather than per component so that tree-shaking still
 * works and so every chart on the dashboard inherits the same typography,
 * grid weight and tooltip behaviour. A dashboard where each chart styles
 * itself always ends up looking like four different products.
 */

import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  TimeScale,
  Title,
  Tooltip,
  type ChartOptions,
} from "chart.js";

ChartJS.register(
  CategoryScale,
  LinearScale,
  TimeScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
  Filler,
);

ChartJS.defaults.font.family =
  "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif";
ChartJS.defaults.font.size = 10;
ChartJS.defaults.animation = false;

/** Read a CSS custom property so charts follow the active theme. */
export function themeColor(variable: string, alpha = 1): string {
  if (typeof window === "undefined") return `hsl(0 0% 50% / ${alpha})`;
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(variable)
    .trim();
  return raw ? `hsl(${raw} / ${alpha})` : `hsl(0 0% 50% / ${alpha})`;
}

export const CHART_COLORS = {
  power: "#22d3ee",
  current: "#a78bfa",
  voltage: "#fbbf24",
  energy: "#34d399",
  cost: "#f472b6",
  reactive: "#fb7185",
} as const;

/**
 * Base options for the streaming line charts.
 *
 * `animation: false` and `pointRadius: 0` are not cosmetic choices: with a new
 * frame arriving every 100 ms at 10x speed, animating each transition would
 * queue more work than the browser can retire and the chart would visibly lag
 * behind the numbers beside it.
 */
export function baseLineOptions(options?: {
  yTitle?: string;
  beginAtZero?: boolean;
  suggestedMax?: number;
}): ChartOptions<"line"> {
  const grid = themeColor("--border", 0.45);
  const text = themeColor("--muted-foreground", 0.95);

  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    layout: { padding: { top: 4, right: 4 } },
    elements: {
      line: { borderWidth: 1.75, tension: 0.32 },
      point: { radius: 0, hoverRadius: 3.5, hitRadius: 8 },
    },
    plugins: {
      legend: {
        display: true,
        position: "top",
        align: "end",
        labels: {
          boxWidth: 8,
          boxHeight: 8,
          usePointStyle: true,
          pointStyle: "circle",
          color: text,
          padding: 12,
        },
      },
      tooltip: {
        backgroundColor: themeColor("--popover", 0.96),
        borderColor: themeColor("--border", 1),
        borderWidth: 1,
        titleColor: themeColor("--foreground", 1),
        bodyColor: text,
        padding: 10,
        cornerRadius: 8,
        displayColors: true,
        boxWidth: 8,
        boxHeight: 8,
        usePointStyle: true,
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: {
          color: text,
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 7,
        },
        border: { color: grid },
      },
      y: {
        beginAtZero: options?.beginAtZero ?? true,
        suggestedMax: options?.suggestedMax,
        grid: { color: grid, drawTicks: false },
        border: { display: false, dash: [3, 4] },
        ticks: { color: text, padding: 6, maxTicksLimit: 6 },
        title: options?.yTitle
          ? {
              display: true,
              text: options.yTitle,
              color: text,
              font: { size: 9, weight: 500 },
            }
          : undefined,
      },
    },
  };
}

export function doughnutOptions(): ChartOptions<"doughnut"> {
  const text = themeColor("--muted-foreground", 0.95);
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { animateRotate: true, duration: 400 },
    cutout: "68%",
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: themeColor("--popover", 0.96),
        borderColor: themeColor("--border", 1),
        borderWidth: 1,
        titleColor: themeColor("--foreground", 1),
        bodyColor: text,
        padding: 10,
        cornerRadius: 8,
        usePointStyle: true,
        boxWidth: 8,
        boxHeight: 8,
      },
    },
  };
}

export function barOptions(yTitle?: string): ChartOptions<"bar"> {
  const grid = themeColor("--border", 0.45);
  const text = themeColor("--muted-foreground", 0.95);
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: themeColor("--popover", 0.96),
        borderColor: themeColor("--border", 1),
        borderWidth: 1,
        titleColor: themeColor("--foreground", 1),
        bodyColor: text,
        padding: 10,
        cornerRadius: 8,
      },
    },
    scales: {
      x: {
        grid: { display: false },
        border: { color: grid },
        ticks: { color: text, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 },
      },
      y: {
        beginAtZero: true,
        grid: { color: grid, drawTicks: false },
        border: { display: false },
        ticks: { color: text, padding: 6, maxTicksLimit: 5 },
        title: yTitle
          ? {
              display: true,
              text: yTitle,
              color: text,
              font: { size: 9, weight: 500 },
            }
          : undefined,
      },
    },
  };
}
