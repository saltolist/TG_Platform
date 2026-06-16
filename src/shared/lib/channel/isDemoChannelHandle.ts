export function isDemoChannelHandle(channel: string): boolean {
  const handle = channel.replace(/^@/, "").toLowerCase();
  return handle === "demochannel" || handle === "demokanal" || handle === "demo_kanal";
}
