import * as React from "react";
import * as TablePrimitive from "@radix-ui/react-table";
import { cn } from "../../lib/utils";

const Table = React.forwardRef<
  React.ElementRef<typeof TablePrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof TablePrimitive.Root>
>(({ className, ...props }, ref) => (
  <TablePrimitive.Root
    ref={ref}
    className={cn("w-full caption-bottom overflow-hidden rounded-lg border border-border/60 bg-card text-sm text-card-foreground", className)}
    {...props}
  />
));
Table.displayName = "Table";

const TableHeader = React.forwardRef<
  React.ElementRef<typeof TablePrimitive.Header>,
  React.ComponentPropsWithoutRef<typeof TablePrimitive.Header>
>(({ className, ...props }, ref) => (
  <TablePrimitive.Header
    ref={ref}
    className={cn("bg-muted/40 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground", className)}
    {...props}
  />
));
TableHeader.displayName = "TableHeader";

const TableRow = React.forwardRef<
  React.ElementRef<typeof TablePrimitive.Row>,
  React.ComponentPropsWithoutRef<typeof TablePrimitive.Row>
>(({ className, ...props }, ref) => (
  <TablePrimitive.Row
    ref={ref}
    className={cn(
      "border-b border-border/40 transition hover:bg-muted/40 data-[state=selected]:bg-muted/40 last:border-0",
      className
    )}
    {...props}
  />
));
TableRow.displayName = "TableRow";

const TableHead = React.forwardRef<
  React.ElementRef<typeof TablePrimitive.ColumnHeaderCell>,
  React.ComponentPropsWithoutRef<typeof TablePrimitive.ColumnHeaderCell>
>(({ className, ...props }, ref) => (
  <TablePrimitive.ColumnHeaderCell
    ref={ref}
    className={cn("px-4 py-3 font-medium", className)}
    {...props}
  />
));
TableHead.displayName = "TableHead";

const TableBody = React.forwardRef<
  React.ElementRef<typeof TablePrimitive.Body>,
  React.ComponentPropsWithoutRef<typeof TablePrimitive.Body>
>(({ className, ...props }, ref) => (
  <TablePrimitive.Body ref={ref} className={cn("divide-y divide-border/40", className)} {...props} />
));
TableBody.displayName = "TableBody";

const TableCell = React.forwardRef<
  React.ElementRef<typeof TablePrimitive.Cell>,
  React.ComponentPropsWithoutRef<typeof TablePrimitive.Cell>
>(({ className, ...props }, ref) => (
  <TablePrimitive.Cell ref={ref} className={cn("px-4 py-3", className)} {...props} />
));
TableCell.displayName = "TableCell";

export { Table, TableHeader, TableRow, TableHead, TableBody, TableCell };
