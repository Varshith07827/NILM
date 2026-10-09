/**
 * Admin: log in, then change the tariff, appliance power ratings and alert
 * thresholds. Rooms and devices are edited on the Rooms & Devices page, which
 * unlocks with the same login.
 */

import {
  BellRing,
  DoorOpen,
  Gauge,
  KeyRound,
  LogOut,
  Plus,
  Receipt,
  RotateCcw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/layout/PageHeader";
import { api } from "@/lib/api";
import { useAuth } from "@/state/auth";
import { useLive } from "@/state/live";
import type { AlertSettings, HouseConfig, Tariff } from "@/types";

function errorText(exc: unknown): string {
  return exc instanceof Error ? exc.message : String(exc);
}

export default function AdminPage() {
  const { admin, logout } = useAuth();

  return (
    <div className="space-y-4">
      <PageHeader
        icon={ShieldCheck}
        title="Admin"
        description="Change what the house costs and how it is set up: the electricity tariff, each appliance's power rating, and when to raise alerts."
        actions={
          admin ? (
            <>
              <Badge variant="success">signed in as {admin.username}</Badge>
              <Button size="sm" variant="outline" onClick={logout}>
                <LogOut className="h-3.5 w-3.5" />
                Log out
              </Button>
            </>
          ) : null
        }
      />
      {admin ? <AdminTools /> : <LoginCard />}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Login
// --------------------------------------------------------------------------- //

function LoginCard() {
  const { login } = useAuth();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [setup, setSetup] = useState<{ configured: boolean; command: string } | null>(null);

  useEffect(() => {
    void api
      .authStatus()
      .then((s) => setSetup({ configured: s.admin_configured, command: s.setup_command }))
      .catch(() => undefined);
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      setPassword("");
    } catch (exc) {
      setError(errorText(exc));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="max-w-sm">
      <CardHeader className="pb-3">
        <CardTitle>
          <KeyRound className="h-3.5 w-3.5 text-primary" />
          Admin login
        </CardTitle>
      </CardHeader>
      <CardContent>
        {setup && !setup.configured ? (
          <div className="space-y-2 text-xs text-muted-foreground">
            <p>No admin account has been set up yet. On the machine running the backend, run:</p>
            <pre className="overflow-x-auto rounded-md bg-secondary/60 px-2.5 py-2 font-mono text-[0.68rem] text-foreground">
              {setup.command}
            </pre>
            <p>then come back and log in.</p>
          </div>
        ) : (
          <form className="space-y-3" onSubmit={(event) => void submit(event)}>
            <label className="block space-y-1">
              <span className="label-muted">Username</span>
              <Input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                required
              />
            </label>
            <label className="block space-y-1">
              <span className="label-muted">Password</span>
              <Input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            {error ? <p className="text-xs text-destructive">{error}</p> : null}
            <Button type="submit" className="w-full" disabled={busy || !password}>
              Log in
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

// --------------------------------------------------------------------------- //
// Tools
// --------------------------------------------------------------------------- //

function AdminTools() {
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <TariffEditor />
      <RatingsEditor />
      <AlertEditor />
      <Card>
        <CardHeader className="pb-3">
          <CardTitle>
            <DoorOpen className="h-3.5 w-3.5 text-primary" />
            Rooms and devices
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-xs text-muted-foreground">
          <p>
            Add rooms, put a fan in each, move or remove devices. Up to five devices of
            one type can share the house: the most a single mains sensor can tell apart.
          </p>
          <Button asChild size="sm" variant="outline">
            <Link to="/rooms">Open Rooms &amp; Devices</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

function Status({ message }: { message: { ok: boolean; text: string } | null }) {
  if (!message) return null;
  return (
    <p className={message.ok ? "text-xs text-success" : "text-xs text-destructive"}>
      {message.text}
    </p>
  );
}

// --- tariff --------------------------------------------------------------- //

interface SlabDraft {
  upTo: string;
  rate: string;
}

function TariffEditor() {
  const { onChanged } = useLive();
  const [presets, setPresets] = useState<Tariff[]>([]);
  const [current, setCurrent] = useState<Tariff | null>(null);
  const [name, setName] = useState("");
  const [fixed, setFixed] = useState("0");
  const [slabs, setSlabs] = useState<SlabDraft[]>([]);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const loadDraft = useCallback((tariff: Tariff) => {
    setName(tariff.name);
    setFixed(String(tariff.fixed_charge_inr));
    setSlabs(
      tariff.slabs.map((slab) => ({
        upTo: slab.up_to_kwh === null ? "" : String(slab.up_to_kwh),
        rate: String(slab.rate_inr),
      })),
    );
  }, []);

  useEffect(() => {
    void api.tariffs().then(setPresets).catch(() => undefined);
    void api
      .settings()
      .then((settings) => {
        setCurrent(settings.tariff);
        loadDraft(settings.tariff);
      })
      .catch(() => undefined);
  }, [loadDraft]);

  const symbol = current?.currency_symbol ?? "₹";

  const applyPreset = async (id: string) => {
    setMessage(null);
    try {
      const response = await api.setTariff({ tariff_id: id });
      const tariff = presets.find((t) => t.id === id) ?? null;
      setCurrent(tariff);
      if (tariff) loadDraft(tariff);
      setMessage({ ok: true, text: response.message });
      onChanged();
    } catch (exc) {
      setMessage({ ok: false, text: errorText(exc) });
    }
  };

  const saveCustom = async (event: FormEvent) => {
    event.preventDefault();
    setMessage(null);
    try {
      const response = await api.setTariff({
        name: name.trim() || "Custom Tariff",
        fixed_charge_inr: Number(fixed) || 0,
        slabs: slabs.map((slab, index) => ({
          up_to_kwh: index === slabs.length - 1 || slab.upTo === "" ? null : Number(slab.upTo),
          rate_inr: Number(slab.rate),
        })),
      });
      setMessage({ ok: true, text: response.message });
      void api.settings().then((settings) => setCurrent(settings.tariff));
      onChanged();
    } catch (exc) {
      setMessage({ ok: false, text: errorText(exc) });
    }
  };

  const updateSlab = (index: number, patch: Partial<SlabDraft>) =>
    setSlabs((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle>
          <Receipt className="h-3.5 w-3.5 text-primary" />
          Electricity tariff
        </CardTitle>
        <p className="text-[0.68rem] text-muted-foreground">
          Current: <span className="font-medium text-foreground">{current?.name ?? "—"}</span>.
          Changing it reprices this month so far.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <span className="label-muted">Use a preset</span>
          <Select onValueChange={(value) => void applyPreset(value)}>
            <SelectTrigger>
              <SelectValue placeholder="Choose a preset tariff" />
            </SelectTrigger>
            <SelectContent>
              {presets.map((tariff) => (
                <SelectItem key={tariff.id} value={tariff.id}>
                  {tariff.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <form className="space-y-2" onSubmit={(event) => void saveCustom(event)}>
          <span className="label-muted">Or set your own rates</span>
          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1">
              <span className="text-[0.66rem] text-muted-foreground">Name</span>
              <Input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="text-[0.66rem] text-muted-foreground">
                Fixed charge ({symbol}/month)
              </span>
              <Input
                type="number"
                min={0}
                step="any"
                value={fixed}
                onChange={(e) => setFixed(e.target.value)}
              />
            </label>
          </div>

          <div className="space-y-1.5">
            <div className="grid grid-cols-[1fr_1fr_auto] gap-2 text-[0.62rem] text-muted-foreground">
              <span>Up to (units this month)</span>
              <span>Rate ({symbol}/unit)</span>
              <span className="w-7" />
            </div>
            {slabs.map((slab, index) => {
              const last = index === slabs.length - 1;
              return (
                <div key={index} className="grid grid-cols-[1fr_1fr_auto] gap-2">
                  <Input
                    type="number"
                    min={0}
                    step="any"
                    value={last ? "" : slab.upTo}
                    placeholder={last ? "and above" : "kWh"}
                    disabled={last}
                    required={!last}
                    onChange={(e) => updateSlab(index, { upTo: e.target.value })}
                  />
                  <Input
                    type="number"
                    min={0}
                    max={1000}
                    step="any"
                    value={slab.rate}
                    required
                    onChange={(e) => updateSlab(index, { rate: e.target.value })}
                  />
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="ghost"
                    disabled={slabs.length <= 1}
                    aria-label="Remove slab"
                    onClick={() => setSlabs((rows) => rows.filter((_, i) => i !== index))}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              );
            })}
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() =>
                setSlabs((rows) => [
                  ...rows.slice(0, -1),
                  { upTo: "", rate: rows.at(-1)?.rate ?? "0" },
                  rows.at(-1) ?? { upTo: "", rate: "0" },
                ])
              }
            >
              <Plus className="h-3 w-3" />
              Add slab
            </Button>
          </div>
          <Status message={message} />
          <Button type="submit" size="sm" disabled={!slabs.length}>
            Save tariff
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

// --- ratings -------------------------------------------------------------- //

function RatingsEditor() {
  const { onChanged } = useLive();
  const [house, setHouse] = useState<HouseConfig | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const reload = useCallback(async () => {
    const config = await api.house();
    setHouse(config);
    setDrafts(Object.fromEntries(config.devices.map((d) => [d.id, String(d.rated_power_w)])));
  }, []);

  useEffect(() => {
    void reload().catch(() => undefined);
  }, [reload]);

  const save = async (deviceId: string, watts: number | null) => {
    setMessage(null);
    try {
      const response = await api.updateDevice(deviceId, { rated_power_w: watts });
      setMessage({ ok: true, text: response.message });
      onChanged();
    } catch (exc) {
      setMessage({ ok: false, text: errorText(exc) });
    } finally {
      await reload().catch(() => undefined);
    }
  };

  const types = Object.fromEntries((house?.types ?? []).map((t) => [t.id, t]));
  const rooms = Object.fromEntries((house?.rooms ?? []).map((r) => [r.id, r.name]));

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle>
          <Gauge className="h-3.5 w-3.5 text-primary" />
          Power ratings
        </CardTitle>
        <p className="text-[0.68rem] text-muted-foreground">
          The nameplate wattage of each device. It sets how much current the device draws
          and how its share of the bill is worked out. Limited to 50–200% of the catalogue
          rating, the range the model was trained around.
        </p>
      </CardHeader>
      <CardContent className="space-y-1.5">
        {house?.devices.map((device) => {
          const type = types[device.type_id];
          const draft = drafts[device.id] ?? "";
          const value = Number(draft);
          const valid =
            draft !== "" && type && value >= type.min_power_w && value <= type.max_power_w;
          const changed = draft !== String(device.rated_power_w);
          return (
            <form
              key={device.id}
              className="flex items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (valid) void save(device.id, value);
              }}
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-[0.72rem] font-medium">{device.name}</p>
                <p className="truncate text-[0.6rem] text-muted-foreground">
                  {rooms[device.room_id]} · catalogue {device.catalogue_power_w} W
                </p>
              </div>
              <Input
                type="number"
                step="any"
                min={type?.min_power_w}
                max={type?.max_power_w}
                value={draft}
                onChange={(e) => setDrafts((d) => ({ ...d, [device.id]: e.target.value }))}
                className="h-7 w-20"
                aria-label={`${device.name} rating in watts`}
              />
              <span className="text-[0.62rem] text-muted-foreground">W</span>
              <Button size="sm" type="submit" className="h-7" disabled={!valid || !changed}>
                Save
              </Button>
              <Button
                size="icon-sm"
                type="button"
                variant="ghost"
                disabled={!device.custom_rating}
                aria-label={`Reset ${device.name} to the catalogue rating`}
                onClick={() => void save(device.id, null)}
              >
                <RotateCcw className="h-3 w-3" />
              </Button>
            </form>
          );
        })}
        <Status message={message} />
      </CardContent>
    </Card>
  );
}

// --- alerts --------------------------------------------------------------- //

const ALERT_FIELDS: { key: keyof AlertSettings; label: string; unit: string }[] = [
  { key: "high_power_threshold_w", label: "High power warning", unit: "W" },
  { key: "sanctioned_load_w", label: "Sanctioned load", unit: "W" },
  { key: "peak_current_alert_a", label: "Current surge", unit: "A" },
  { key: "daily_cost_alert_inr", label: "Daily budget", unit: "₹" },
];

function AlertEditor() {
  const [values, setValues] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    void api
      .settings()
      .then((settings) =>
        setValues(
          Object.fromEntries(
            ALERT_FIELDS.map((f) => [f.key, String(settings.alerts[f.key])]),
          ),
        ),
      )
      .catch(() => undefined);
  }, []);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setMessage(null);
    try {
      const response = await api.setAlerts(
        Object.fromEntries(ALERT_FIELDS.map((f) => [f.key, Number(values[f.key])])),
      );
      setMessage({ ok: true, text: response.message });
    } catch (exc) {
      setMessage({ ok: false, text: errorText(exc) });
    }
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle>
          <BellRing className="h-3.5 w-3.5 text-primary" />
          Alert thresholds
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form className="space-y-2" onSubmit={(event) => void save(event)}>
          {ALERT_FIELDS.map((field) => (
            <label key={field.key} className="flex items-center gap-2">
              <span className="flex-1 text-[0.72rem]">{field.label}</span>
              <Input
                type="number"
                min={0}
                step="any"
                required
                value={values[field.key] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
                className="h-7 w-28"
              />
              <span className="w-4 text-[0.62rem] text-muted-foreground">{field.unit}</span>
            </label>
          ))}
          <Status message={message} />
          <Button type="submit" size="sm">
            Save thresholds
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
