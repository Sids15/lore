import markUrl from "../assets/lore-mark.png";

/** The Lore stacked-L mark, from the brand artwork. Inverts to dark ink on the light theme. */
export function LoreMark({ size = 20 }: { size?: number }) {
  return <img className="loremark" src={markUrl} alt="" aria-hidden height={size} />;
}
