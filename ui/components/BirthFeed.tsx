// Ephemeral glance feed: what the brain just remembered, in words —
// the node pop means nothing on video unless viewers can read the memory.
export interface FeedItem {
  key: number;
  op: string;
  text: string;
}

export default function BirthFeed({ items }: { items: FeedItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="flex flex-col gap-1 items-end">
      {items.map((it) => (
        <div key={it.key} className="card px-2 py-1 text-xs max-w-[340px]">
          <span className={`chip op-${it.op}`}>{it.op}</span>{" "}
          <span>{it.text}</span>
        </div>
      ))}
    </div>
  );
}
