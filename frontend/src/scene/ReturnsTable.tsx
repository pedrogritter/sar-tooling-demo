import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatMeasure } from "@/lib/format"
import type { ReturnRow } from "@/scene/rows"

interface ReturnsTableProps {
  rows: ReturnRow[]
}

export function ReturnsTable({ rows }: ReturnsTableProps) {
  return (
    <Table>
      <TableCaption className="caption-top mt-0 mb-3 text-left">
        Bright returns. Motion is displacement during the dwell, not a vessel
        name.
      </TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Row</TableHead>
          <TableHead>Motion</TableHead>
          <TableHead className="text-right">Area</TableHead>
          <TableHead className="text-right">Speed</TableHead>
          <TableHead className="text-right">Displacement</TableHead>
          <TableHead className="text-right">Peak sigma0</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.length === 0 ? (
          <TableRow>
            <TableCell colSpan={6} className="text-muted-foreground">
              No bright returns in this measurement.
            </TableCell>
          </TableRow>
        ) : (
          rows.map((row, index) => (
            <TableRow key={row.id}>
              <TableCell className="font-medium">
                Bright return {index + 1}
              </TableCell>
              <TableCell>{row.motion}</TableCell>
              <TableCell className="text-right tabular-nums">
                {formatMeasure(row.areaM2, "m2")}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatMeasure(row.speedMS, "m/s")}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatMeasure(row.displacementM, "m")}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatMeasure(row.peakSigma0Db, "dB")}
              </TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  )
}
