/**
 * Rooms and the devices in them.
 *
 * Everyone can see the layout and what each device is drawing; changing it
 * (adding rooms, adding a fan to a room, moving or removing devices) needs the
 * admin login. Changes reach the running simulation immediately.
 */

import { DoorOpen, Lock, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
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
import { ApiError, api } from "@/lib/api";
import { applianceIcon } from "@/lib/icons";
import { cn, formatPower } from "@/lib/utils";
import { useAuth } from "@/state/auth";
import { useLive } from "@/state/live";
import type { HouseConfig, HouseRoom, HouseType } from "@/types";

export default function RoomsPage() {
  const { admin } = useAuth();
  const { frame } = useLive();
  const [house, setHouse] = useState<HouseConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newRoom, setNewRoom] = useState("");

  const reload = useCallback(async () => {
    try {
      setHouse(await api.house());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** Run a change, surface its error, and reload the house either way. */
  const change = useCallback(
    async (action: () => Promise<unknown>) => {
      setError(null);
      try {
        await action();
      } catch (exc) {
        setError(exc instanceof ApiError || exc instanceof Error ? exc.message : String(exc));
      } finally {
        await reload();
      }
    },
    [reload],
  );

  const live = useMemo(
    () => Object.fromEntries((frame?.appliances ?? []).map((a) => [a.id, a])),
    [frame?.appliances],
  );

  return (
    <div className="space-y-4">
      <PageHeader
        icon={DoorOpen}
        title="Rooms & Devices"
        description="The rooms of the house and the devices in each. Several devices of one type -- a fan in every room -- are told apart by their switching signatures."
        actions={
          admin ? (
            <form
              className="flex items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (!newRoom.trim()) return;
                void change(() => api.addRoom(newRoom.trim())).then(() => setNewRoom(""));
              }}
            >
              <Input
                value={newRoom}
                onChange={(event) => setNewRoom(event.target.value)}
                placeholder="New room name"
                maxLength={48}
                className="w-44"
              />
              <Button size="sm" type="submit" disabled={!newRoom.trim()}>
                <Plus className="h-3.5 w-3.5" />
                Add room
              </Button>
            </form>
          ) : (
            <Button asChild size="sm" variant="outline">
              <Link to="/admin">
                <Lock className="h-3.5 w-3.5" />
                Log in to edit
              </Link>
            </Button>
          )
        }
      />

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        {house?.rooms.map((room) => (
          <RoomCard
            key={room.id}
            room={room}
            house={house}
            live={live}
            editable={Boolean(admin)}
            onChange={change}
          />
        ))}
      </div>
    </div>
  );
}

function RoomCard({
  room,
  house,
  live,
  editable,
  onChange,
}: {
  room: HouseRoom;
  house: HouseConfig;
  live: Record<string, { estimated_power_w: number; detected: boolean } | undefined>;
  editable: boolean;
  onChange: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const devices = house.devices.filter((d) => d.room_id === room.id);
  const typesById = Object.fromEntries(house.types.map((t) => [t.id, t]));
  const roomWatts = devices.reduce(
    (sum, d) => sum + (live[d.id]?.detected ? (live[d.id]?.estimated_power_w ?? 0) : 0),
    0,
  );
  const watts = formatPower(roomWatts);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="min-w-0">
          <DoorOpen className="h-3.5 w-3.5 shrink-0 text-primary" />
          <span className="truncate">{room.name}</span>
        </CardTitle>
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold tabular-nums">
            {watts.value}
            <span className="ml-0.5 text-[0.62rem] font-normal text-muted-foreground">
              {watts.unit}
            </span>
          </span>
          {editable ? (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  const name = window.prompt("Rename room", room.name);
                  if (name && name.trim() && name.trim() !== room.name) {
                    void onChange(() => api.renameRoom(room.id, name.trim()));
                  }
                }}
              >
                Rename
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={`Remove ${room.name}`}
                onClick={() => {
                  const extra = devices.length
                    ? ` and its ${devices.length} device${devices.length === 1 ? "" : "s"}`
                    : "";
                  if (window.confirm(`Remove ${room.name}${extra}?`)) {
                    void onChange(() => api.deleteRoom(room.id));
                  }
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-1.5">
        {devices.length === 0 ? (
          <p className="py-2 text-xs text-muted-foreground">No devices yet.</p>
        ) : null}
        {devices.map((device) => {
          const type = typesById[device.type_id];
          const Icon = applianceIcon(type?.icon ?? "");
          const state = live[device.id];
          const devicePower = formatPower(state?.detected ? state.estimated_power_w : 0);
          return (
            <div
              key={device.id}
              className={cn(
                "rounded-md border border-border/40 px-2 py-1.5",
                state?.detected && "bg-secondary/40",
              )}
            >
              <div className="flex items-center gap-2">
                <Icon
                  className="h-3.5 w-3.5 shrink-0"
                  style={{ color: state?.detected ? type?.colour : undefined }}
                />
                <Link
                  to={`/appliances/${encodeURIComponent(device.id)}`}
                  className="min-w-0 flex-1 truncate text-[0.72rem] font-medium hover:text-primary hover:underline"
                  title={device.name}
                >
                  {device.name}
                </Link>
                <span className="shrink-0 font-mono text-[0.68rem] tabular-nums">
                  {state?.detected ? `${devicePower.value} ${devicePower.unit}` : "off"}
                </span>
              </div>
              <div className="mt-1 flex items-center gap-2 pl-[22px]">
                <span className="flex-1 text-[0.6rem] text-muted-foreground">
                  rated {device.rated_power_w} W
                  {device.custom_rating ? ` (catalogue ${device.catalogue_power_w} W)` : ""}
                </span>
                {editable ? (
                  <>
                    <Select
                      value={device.room_id}
                      onValueChange={(value) =>
                        void onChange(() => api.updateDevice(device.id, { room_id: value }))
                      }
                    >
                      <SelectTrigger
                        className="h-6 w-28 text-[0.62rem]"
                        aria-label={`Move ${device.name} to another room`}
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {house.rooms.map((r) => (
                          <SelectItem key={r.id} value={r.id}>
                            {r.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      className="h-6 w-6"
                      aria-label={`Remove ${device.name}`}
                      onClick={() => {
                        if (window.confirm(`Remove ${device.name}?`)) {
                          void onChange(() => api.deleteDevice(device.id));
                        }
                      }}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </>
                ) : null}
              </div>
            </div>
          );
        })}
        {editable ? (
          <AddDevice room={room} types={house.types} onChange={onChange} />
        ) : null}
      </CardContent>
    </Card>
  );
}

function AddDevice({
  room,
  types,
  onChange,
}: {
  room: HouseRoom;
  types: HouseType[];
  onChange: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [typeId, setTypeId] = useState("");
  const [rating, setRating] = useState("");
  const type = types.find((t) => t.id === typeId);

  return (
    <form
      className="flex flex-wrap items-center gap-1.5 pt-1.5"
      onSubmit={(event) => {
        event.preventDefault();
        if (!type) return;
        const watts = rating ? Number(rating) : undefined;
        void onChange(() =>
          api.addDevice({ type_id: type.id, room_id: room.id, rated_power_w: watts }),
        ).then(() => {
          setTypeId("");
          setRating("");
        });
      }}
    >
      <Select value={typeId} onValueChange={setTypeId}>
        <SelectTrigger className="h-7 min-w-0 flex-1 text-[0.68rem]">
          <SelectValue placeholder="Add a device…" />
        </SelectTrigger>
        <SelectContent>
          {types.map((t) => (
            <SelectItem key={t.id} value={t.id} disabled={t.device_count >= t.max_devices}>
              {t.name}
              {t.device_count >= t.max_devices ? ` (limit ${t.max_devices})` : ""}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Input
        type="number"
        inputMode="decimal"
        value={rating}
        onChange={(event) => setRating(event.target.value)}
        placeholder={type ? `${type.rated_power_w} W` : "Rating W"}
        min={type?.min_power_w}
        max={type?.max_power_w}
        step="any"
        className="h-7 w-24"
        aria-label="Rated power in watts (optional)"
      />
      <Button size="sm" type="submit" disabled={!type} className="h-7">
        <Plus className="h-3 w-3" />
        Add
      </Button>
      {type ? (
        <Badge variant="outline" className="basis-full justify-center sm:basis-auto">
          {type.device_count}/{type.max_devices} {type.name.toLowerCase()}s · {type.min_power_w}-
          {type.max_power_w} W
        </Badge>
      ) : null}
    </form>
  );
}
