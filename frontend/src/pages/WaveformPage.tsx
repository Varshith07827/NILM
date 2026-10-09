import { Radar, Waves } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Bar } from "react-chartjs-2";

import { Oscilloscope } from "@/components/Oscilloscope";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/layout/PageHeader";
import { api } from "@/lib/api";
import { barOptions } from "@/lib/charts";
import { hexToRgba } from "@/lib/utils";
import { useLive } from "@/state/live";

interface SignatureRow {
  id: string;
  name: string;
  rated_power_w: number;
  harmonics: Record<string, { magnitude_a: number; phase_deg: number }>;
}

export default function Analytics() {
  const { frame } = useLive();
  const [signatures, setSignatures] = useState<SignatureRow[]>([]);
  const [orders, setOrders] = useState<number[]>([1, 3, 5, 7, 9, 11, 13]);
  const [selected, setSelected] = useState<string>("tv");

  useEffect(() => {
    void api
      .signatures()
      .then((response) => {
        setOrders(response.orders);
        setSignatures(response.appliances as SignatureRow[]);
      })
      .catch(() => undefined);
  }, []);

  const current = signatures.find((row) => row.id === selected);

  /**
   * Harmonic magnitudes normalised to the fundamental, which is how the model
   * sees them. Plotting absolute amps would just rank appliances by size and
   * hide the shape difference that actually separates them.
   */
  const chart = useMemo(() => {
    if (!current) return null;
    const fundamental = current.harmonics.h1?.magnitude_a ?? 1;
    return {
      labels: orders.map((order) => `H${order}`),
      datasets: [
        {
          label: "Relative amplitude",
          data: orders.map((order) => {
            const entry = current.harmonics[`h${order}`];
            return entry ? entry.magnitude_a / fundamental : 0;
          }),
          backgroundColor: hexToRgba("#22d3ee", 0.55),
          hoverBackgroundColor: hexToRgba("#22d3ee", 0.85),
          borderRadius: 3,
          borderSkipped: false as const,
        },
      ],
    };
  }, [current, orders]);

  return (
    <div className="space-y-4">
      <PageHeader
        icon={Waves}
        title="Waveform & Harmonics"
        description="The raw mains signal and the frequency-domain structure the classifier keys on."
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Oscilloscope frame={frame} />

        <Card>
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <CardTitle>
                  <Radar className="h-3.5 w-3.5 text-primary" />
                  Harmonic Fingerprint
                </CardTitle>
                <p className="mt-1 text-[0.68rem] text-muted-foreground">
                  Odd harmonics relative to the fundamental
                </p>
              </div>
              <Select value={selected} onValueChange={setSelected}>
                <SelectTrigger className="w-[168px]">
                  <SelectValue placeholder="Choose an appliance" />
                </SelectTrigger>
                <SelectContent>
                  {signatures.map((row) => (
                    <SelectItem key={row.id} value={row.id}>
                      {row.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardHeader>
          <CardContent>
            <div className="h-[200px]">
              {chart ? (
                <Bar data={chart} options={barOptions("× fundamental")} />
              ) : (
                <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                  Loading signatures…
                </div>
              )}
            </div>
            <p className="mt-2 text-[0.68rem] leading-relaxed text-muted-foreground">
              This is the appliance&apos;s identity. A motor load is almost all
              fundamental with negligible harmonics; a switched-mode supply
              carries 3rd and 5th harmonics at more than half the fundamental.
              Two appliances with the same RMS current and the same power factor
              can still look completely different here — which is exactly why
              disaggregation from one sensor is possible at all.
            </p>
          </CardContent>
        </Card>
      </div>

    </div>
  );
}
