/**
 * CarPicker — grouped, searchable combobox for selecting a car.
 *
 * Uses the cmdk Command primitives (same library as CommandPalette.tsx).
 * Built as a Popover + Command (not a full-screen dialog) so it can be
 * embedded inline in pages and forms.
 *
 * Archived cars ordering note: the CarPayload has no "archived_at" timestamp.
 * We approximate "newest-archived-first" by sorting archived cars by
 * descending `id`, on the assumption that higher ids were created later.
 */
import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import type { CarPayload } from '@/api/client'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { cn } from '@/lib/cn'

export interface CarPickerProps {
  /** Currently selected car id, or null when "All cars" is selected. */
  value: number | null
  /** Called with the new car id (or null for "All cars"). */
  onChange: (carId: number | null) => void
  /** Full list of cars (active + archived). */
  cars: CarPayload[]
  /**
   * When true, archived cars are shown in a collapsed group (behind a
   * "Show archived (N)" reveal). When false/omitted, archived cars are
   * never shown regardless of what is in `cars`.
   */
  includeArchived?: boolean
  /**
   * When true, an "All cars" option (value null) is prepended to the
   * active group. Intended for the Sessions list filter.
   */
  allowAll?: boolean
  /** data-testid placed on the trigger button for testing. */
  'data-testid'?: string
}

export default function CarPicker({
  value,
  onChange,
  cars,
  includeArchived = false,
  allowAll = false,
  'data-testid': dataTestId,
}: CarPickerProps) {
  const [open, setOpen] = useState(false)
  const [showArchived, setShowArchived] = useState(false)

  // Split into active and archived.
  const activeCars = cars.filter((c) => c.active)
  // Approximate newest-archived-first by descending id (no archived_at timestamp).
  const archivedCars = includeArchived
    ? cars.filter((c) => !c.active).sort((a, b) => b.id - a.id)
    : []

  // Compute the trigger label.
  const selectedCar = cars.find((c) => c.id === value)
  let triggerLabel: string
  if (value === null) {
    triggerLabel = allowAll ? 'All cars' : 'Select a car'
  } else if (selectedCar) {
    triggerLabel = selectedCar.active
      ? selectedCar.display_name
      : `${selectedCar.display_name} (archived)`
  } else {
    triggerLabel = `Car #${value}`
  }

  function handleSelect(carId: number | null) {
    onChange(carId)
    setOpen(false)
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          data-testid={dataTestId}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition',
            'border-slate-200 bg-white text-slate-600 hover:bg-slate-50',
            'dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800',
          )}
        >
          {triggerLabel}
          <ChevronDown className="h-3.5 w-3.5" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-0" align="start">
        <Command>
          <CommandInput
            placeholder="Search cars…"
            aria-label="Search cars"
          />
          <CommandList>
            <CommandEmpty>No cars found.</CommandEmpty>
            <CommandGroup>
              {allowAll && (
                <CommandItem
                  value="__all__"
                  onSelect={() => handleSelect(null)}
                >
                  All cars
                </CommandItem>
              )}
              {activeCars.map((car) => (
                <CommandItem
                  key={car.id}
                  value={car.display_name}
                  onSelect={() => handleSelect(car.id)}
                >
                  {car.display_name}
                </CommandItem>
              ))}
            </CommandGroup>

            {includeArchived && archivedCars.length > 0 && (
              <>
                <CommandSeparator />
                {!showArchived ? (
                  <CommandGroup>
                    <button
                      type="button"
                      className="w-full px-2 py-1.5 text-left text-xs text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
                      onClick={(e) => {
                        e.stopPropagation()
                        setShowArchived(true)
                      }}
                    >
                      Show archived ({archivedCars.length})
                    </button>
                  </CommandGroup>
                ) : (
                  <CommandGroup heading="Archived">
                    {archivedCars.map((car) => (
                      <CommandItem
                        key={car.id}
                        value={`${car.display_name} (archived)`}
                        onSelect={() => handleSelect(car.id)}
                      >
                        {car.display_name} (archived)
                      </CommandItem>
                    ))}
                  </CommandGroup>
                )}
              </>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
