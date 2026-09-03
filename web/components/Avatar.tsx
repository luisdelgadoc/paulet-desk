import { avatarColor, initials } from "@/lib/avatar";

export default function Avatar({
  name,
  phone,
  size = 40,
}: {
  name: string | null;
  phone: string;
  size?: number;
}) {
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-full font-medium text-white"
      style={{
        width: size,
        height: size,
        backgroundColor: avatarColor(phone),
        fontSize: size * 0.4,
      }}
    >
      {initials(name, phone)}
    </div>
  );
}
