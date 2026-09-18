import { Boxes, Table2 } from "lucide-react";
import { useEffect, useState } from "react";

import { ApplianceGrid } from "@/components/ApplianceGrid";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { InfoTip } from "@/components/ui/tooltip";
import { PageHeader } from "@/components/layout/PageHeader";
import { api } from "@/lib/api";
import { useLive } from "@/state/live";
import type { ApplianceSpec } from "@/types";

export default function Appliances() {
  const { frame, showTruth, setShowTruth, onChanged } = useLive();
  const [catalogue, setCatalogue] = useState<ApplianceSpec[]>([]);

  useEffect(() => {
    void api
      .appliances()
      .then(setCatalogue)
      .catch(() => undefined);
  }, []);

  return (
    <div className="space-y-4">
      <PageHeader
        icon={Boxes}
        title="Appliances"
        description="What the detector currently believes is running, with the electrical signature that makes each appliance identifiable."
      />

      <ApplianceGrid
        appliances={frame?.appliances ?? []}
        showTruth={showTruth}
        onToggleTruth={setShowTruth}
        onChanged={onChanged}
      />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle>
            <Table2 className="h-3.5 w-3.5 text-primary" />
            Electrical Signatures
          </CardTitle>
          <p className="text-xs leading-relaxed text-muted-foreground">
            Every value below is <em>derived</em> from the appliance nameplate,
            not hand-tuned — the same numbers drive the waveform synthesis. The
            separation between the two right-hand columns is the physical basis
            for disaggregating a single measurement: motors sit near a crest
            factor of 1.41 with low distortion, switched-mode supplies sit far
            above it.
          </p>
        </CardHeader>
        <CardContent>
          <ScrollArea className="max-h-[520px]">
            <table className="w-full text-[0.7rem]">
              <thead className="sticky top-0 z-10 bg-card/95 text-muted-foreground backdrop-blur">
                <tr className="border-b border-border/60">
                  <th className="py-2 text-left font-medium">Appliance</th>
                  <th className="py-2 text-left font-medium">Load type</th>
                  <th className="py-2 text-right font-medium">Rated</th>
                  <th className="py-2 text-right font-medium">Current</th>
                  <th className="py-2 text-right font-medium">PF</th>
                  <th className="py-2 text-right font-medium">
                    <InfoTip label="Power factor caused purely by the fundamental phase shift — the motor-like component.">
                      <span className="cursor-help underline decoration-dotted">
                        PF disp
                      </span>
                    </InfoTip>
                  </th>
                  <th className="py-2 text-right font-medium">
                    <InfoTip label="Power factor caused purely by harmonic distortion — the switched-mode component.">
                      <span className="cursor-help underline decoration-dotted">
                        PF dist
                      </span>
                    </InfoTip>
                  </th>
                  <th className="py-2 text-right font-medium">Phase</th>
                  <th className="py-2 text-right font-medium">THD</th>
                  <th className="py-2 text-right font-medium">
                    <InfoTip label="Peak inrush current at switch-on, as a multiple of the steady running current.">
                      <span className="cursor-help underline decoration-dotted">
                        Inrush
                      </span>
                    </InfoTip>
                  </th>
                </tr>
              </thead>
              <tbody>
                {catalogue.map((spec) => (
                  <tr
                    key={spec.id}
                    className="border-b border-border/25 transition-colors hover:bg-secondary/30"
                  >
                    <td className="py-1.5">
                      <span className="flex items-center gap-1.5">
                        <span
                          className="h-2 w-2 shrink-0 rounded-full"
                          style={{ background: spec.colour }}
                        />
                        <span className="truncate font-medium">{spec.name}</span>
                      </span>
                    </td>
                    <td className="py-1.5">
                      <Badge
                        variant={
                          spec.load_type === "smps" ? "accent" : "secondary"
                        }
                        className="px-1.5 py-0 text-[0.6rem]"
                      >
                        {spec.load_type.replace(/_/g, " ")}
                      </Badge>
                    </td>
                    <td className="py-1.5 text-right font-mono tabular-nums">
                      {spec.rated_power_w} W
                    </td>
                    <td className="py-1.5 text-right font-mono tabular-nums">
                      {spec.rms_current_a.toFixed(3)} A
                    </td>
                    <td className="py-1.5 text-right font-mono tabular-nums">
                      {spec.power_factor.toFixed(2)}
                    </td>
                    <td className="py-1.5 text-right font-mono tabular-nums text-muted-foreground">
                      {spec.displacement_power_factor.toFixed(3)}
                    </td>
                    <td className="py-1.5 text-right font-mono tabular-nums text-muted-foreground">
                      {spec.distortion_power_factor.toFixed(3)}
                    </td>
                    <td className="py-1.5 text-right font-mono tabular-nums">
                      {spec.phase_angle_deg.toFixed(1)}°
                    </td>
                    <td
                      className="py-1.5 text-right font-mono tabular-nums"
                      style={{
                        color:
                          spec.thd_percent > 50
                            ? "hsl(var(--accent))"
                            : undefined,
                      }}
                    >
                      {spec.thd_percent.toFixed(0)}%
                    </td>
                    <td className="py-1.5 text-right font-mono tabular-nums">
                      {spec.startup_multiplier.toFixed(1)}×
                    </td>
                  </tr>
                ))}
                {catalogue.length === 0 ? (
                  <tr>
                    <td colSpan={10} className="py-6 text-center text-muted-foreground">
                      Loading catalogue…
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}
