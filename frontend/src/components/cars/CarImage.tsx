import { useState } from 'react'
import { Car as CarIcon } from 'lucide-react'
import { api } from '@/api/client'
import { cn } from '@/lib/cn'

export interface CarImageProps {
  carId: number
  view?: string
  /** Tailwind classes for the wrapper aspect-ratio + size. */
  className?: string
  alt?: string
}

/**
 * Shows the locally-cached pycupra image, falling back to a slate
 * silhouette icon when the API returns 404 (image not yet pulled).
 */
export function CarImage({
  carId,
  view = 'front_cropped',
  className,
  alt = 'Vehicle image',
}: CarImageProps) {
  const [errored, setErrored] = useState(false)
  return (
    <div
      className={cn(
        'flex items-center justify-center overflow-hidden rounded-md bg-slate-100 dark:bg-slate-800',
        className,
      )}
    >
      {errored ? (
        <CarIcon
          className="h-12 w-12 text-slate-400 dark:text-slate-500"
          aria-hidden
        />
      ) : (
        <img
          src={api.carImageUrl(carId, view)}
          alt={alt}
          className="h-full w-full object-contain"
          onError={() => setErrored(true)}
        />
      )}
    </div>
  )
}
