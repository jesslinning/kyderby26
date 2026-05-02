/**
 * In-app glossary — casual explanations for race fans (no raw data file jargon).
 * Section ids keep prefix `def-` for deep links from column headers.
 */
export function DefinitionsTab() {
  return (
    <div className="definitions">
      <section className="card def-card" id="def-horse">
        <h2>Horse</h2>
        <p>
          The name of the runner. Everything on this page lines up by horse so you are always
          comparing the same animal across different predictions.
        </p>
      </section>

      <section className="card def-card" id="def-composite-score">
        <h2>Composite score</h2>
        <p>
          One <strong>overall rating per horse</strong> so you can sort the whole field on a
          single scale. It mixes three ideas: how likely the horse is to finish in the Top 3,
          how likely in the Top 5, and how strongly the finish-position models like the horse.
          This is a <em>rough</em> ranking tool—not a precise “chance to win the Derby” number.
        </p>
        <p>
          Those three pieces are blended using fixed <strong>weights</strong> (by default: half
          from Top 3, forty percent from Top 5, ten percent from finish-position strength). The
          classifiers already speak in chances between 0 and 100%; finish predictions are
          converted to <strong>FP strength</strong> (below) so “expected place” does not drown
          out everything else.
        </p>
        <p>
          If those weights were changed, the order of horses would change too—you would still
          see the same building blocks in the table so nothing is hidden.
        </p>
      </section>

      <section className="card def-card" id="def-ensemble-top3">
        <h2>Ensemble top-3</h2>
        <p>
          The <strong>average likelihood across models</strong> that each predict whether this
          horse will finish in the <strong>Top 3</strong>. Several separate models each output a
          probability for that yes/no question; this column is simply their average—think of it
          as the crowd opinion among those models for a top-three finish.
        </p>
      </section>

      <section className="card def-card" id="def-ensemble-top5">
        <h2>Ensemble top-5</h2>
        <p>
          The same idea as ensemble Top 3, but for finishing in the <strong>Top 5</strong>:
          several models each estimate that chance, and this column averages them. Asking “top
          five?” is easier than “top three?”, so this number is often a bit kinder to longer
          shots than Top 3 alone.
        </p>
      </section>

      <section className="card def-card" id="def-fp-strength">
        <h2>FP strength</h2>
        <p>
          A score from <strong>weak to strong</strong> summarizing what the finish-position models
          expect: each model guesses an expected finishing place (lower place is better). We
          average those guesses, then rank every horse in the field so the best-looking picks
          sit near the top and the weaker ones near the bottom. That keeps finish predictions on
          a similar kind of scale as the Top 3 / Top 5 chances before they are mixed in—with
          only a <strong>small share of the blend</strong> so shaky place estimates do not
          steamroll the rest.
        </p>
      </section>

      <section className="card def-card" id="def-mean-fp-pred">
        <h2>Mean FP pred.</h2>
        <p>
          The <strong>average predicted finishing position</strong> from all the
          finish-position models (each one outputs something like an “expected place” number;
          lower means a better expected finish). This is the raw average before it is turned
          into FP strength—handy for seeing whether those models agree or argue about a horse.
        </p>
      </section>

      <section className="card def-card" id="def-softmax">
        <h2>Softmax</h2>
        <p>
          A way to turn a set of strength scores (one per horse) into a set of <strong>shares
          that add up to 100%</strong>. Horses with higher scores get a bigger share. It is a
          common way to go from “who looks better on paper” to a simple win-style split when you
          do not have a separate win model.
        </p>
        <p>
          The math behind it is a little technical, but the idea is: spread the field’s
          confidence across all entries in a single step, in proportion to how strong each
          horse’s score is.
        </p>
      </section>

      <section className="card def-card" id="def-softmax-chains">
        <h2>Softmax chains (“naive” exotic probabilities)</h2>
        <p>
          For win / place / show, a rough order is often enough. <strong>Exacta, trifecta, and
          superfecta</strong> care about <strong>order</strong> (1st, 2nd, 3rd, 4th). This app
          builds a <em>rough</em> storybook probability by repeating a simple pattern:
        </p>
        <ol className="def-list">
          <li>Pick 1st using a softmax over the <strong>whole</strong> field.</li>
          <li>Remove that horse, then pick 2nd from the <strong>remaining</strong> horses with
            the same style of split.</li>
          <li>Do the same for 3rd and 4th when you are looking at tris and supers.</li>
        </ol>
        <p>
          The <strong>naive probability</strong> you see is the result of that chain. It is
          useful for <strong>comparing one ticket to another</strong> under the same rules—not
          for matching the live betting pool or a full race simulation.
        </p>
      </section>

      <section className="card def-card def-card--compact">
        <h2>More terms (short glossary)</h2>
        <dl className="glossary">
          <dt>Blend weights</dt>
          <dd>How much the overall score leans on Top 3 chance, Top 5 chance, and finish
            strength. If the three weights add up to 1, you can read the composite as a
            straight combination of those three ideas (each scaled so higher = better).</dd>

          <dt>Rankings tab</dt>
          <dd>Full prediction table for the field: composite score plus the building blocks. Tap
            a column header to sort by that number or by name.</dd>

          <dt>Top N (exotic tabs)</dt>
          <dd>Only ordered bets built from the strongest handful of horses (by that screen’s
            score) are listed, to keep the list manageable. Anyone outside that group is left
            out even if they could still hit.</dd>

          <dt>Naive probability</dt>
          <dd>The chained storybook chance for one ordered ticket; it is not the full picture of
            every possible finishing order in the race.</dd>

          <dt>Multiple models</dt>
          <dd>Several automated predictions are averaged or blended for each horse—similar to
            asking a few handicappers and combining their opinions.</dd>

          <dt>Heuristic vs calibrated</dt>
          <dd><strong>Heuristic</strong>: built to be easy to explore and compare.{" "}
            <strong>Calibrated</strong>: tuned to match real-world hit rates over many races
            (not what this tool tries to do).</dd>
        </dl>
      </section>
    </div>
  );
}
