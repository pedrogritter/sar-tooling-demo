import type { Fact } from "@/lib/format"

interface FactListProps {
  facts: Fact[]
  dense?: boolean
}

export function FactList({ facts, dense = false }: FactListProps) {
  return (
    <dl className={dense ? "flex flex-col gap-2" : "flex flex-col gap-3"}>
      {facts.map((fact) => (
        <div
          className={
            dense
              ? "flex flex-col gap-0.5"
              : "grid grid-cols-[6.5rem_minmax(0,1fr)] gap-3"
          }
          key={fact.label}
        >
          <dt className="text-muted-foreground">{fact.label}</dt>
          <dd className={dense ? "text-xs font-medium break-all" : "font-medium break-all"}>
            {fact.value}
          </dd>
        </div>
      ))}
    </dl>
  )
}
