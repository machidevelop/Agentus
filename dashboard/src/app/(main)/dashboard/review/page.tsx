import { reviews } from "./_components/data";
import { Reviews } from "./_components/reviews";

export default function Page() {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-3xl tracking-tight">Finding Review Queue</h2>
        <p className="text-muted-foreground">Manual review required before production deployment.</p>
      </div>
      <Reviews data={reviews} />
    </div>
  );
}
