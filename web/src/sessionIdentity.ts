/** Frontend connection identity only; history and memory remain owned by DSH.
 * A pending creation survives panel suspension, but not an explicit new chat. */
export class SessionIdentity {
  id = ''
  private generation = 0
  private pending?: Promise<string | undefined>
  select(id = '') { this.generation++; this.id = id; this.pending = undefined }
  ensure(create: () => Promise<string>): Promise<string | undefined> {
    if (this.id) return Promise.resolve(this.id)
    if (!this.pending) {
      const generation = this.generation
      const pending = Promise.resolve().then(create).then(id => {
        if (generation !== this.generation) return undefined
        this.id = id
        return id
      }).finally(() => { if (this.pending === pending) this.pending = undefined })
      this.pending = pending
    }
    return this.pending
  }
}
