import { cn } from "@/lib/utils";

export function BugsiftLogo({
  className,
  size = "md",
}: {
  className?: string;
  size?: "sm" | "md" | "lg";
}) {
  const sizes = {
    sm: "text-[13px]",
    md: "text-[15px]",
    lg: "text-[22px]",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center font-sans font-semibold leading-none tracking-[-0.02em] text-foreground",
        sizes[size],
        className,
      )}
      aria-label="bugsift"
    >
      <span aria-hidden>bugs</span>
      <span aria-hidden className="relative">
        <span>ı</span>
        <span
          className="absolute left-1/2 h-[0.22em] w-[0.22em] -translate-x-1/2 rounded-full bg-primary"
          style={{ top: "-0.32em" }}
        />
      </span>
      <span aria-hidden>ft</span>
    </span>
  );
}
