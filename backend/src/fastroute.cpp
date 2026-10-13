// C++ shortest-path search for platetrail.sim.routing (pybind11).
//
// Replaces networkx.single_source_dijkstra in Router._compute and is built to
// return the *same* path, not just an equally short one. It therefore copies
// networkx 3.x's _dijkstra_multisource exactly:
//
// * the heap is ordered by (distance, push counter), so ties pop in push order;
// * neighbours are visited in the graph's adjacency (insertion) order, which the
//   Python side passes in as CSR arrays;
// * a node's tentative distance is replaced only on a strict improvement, and its
//   predecessor is the node that made the last improvement;
// * parallel edges are collapsed to their minimum cost before the search;
// * the search stops when the target is popped.
//
// The origin and destination are virtual nodes, as in the Python version: the
// origin's out-edges are the ways to leave the start point, and nodes with a way
// into the end point get one extra out-edge to the destination, visited after
// their regular neighbours (networkx appends it last to their adjacency).
//
// Distances are IEEE doubles summed in the same order as Python, so costs match
// bit for bit. Do not build with -ffast-math.

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <cstdint>
#include <limits>
#include <optional>
#include <queue>
#include <stdexcept>
#include <utility>
#include <vector>

namespace py = pybind11;

namespace {

struct Entry {
    double dist;
    std::uint64_t counter;
    std::int32_t node;
};

struct Later {  // min-heap on (dist, counter)
    bool operator()(const Entry& a, const Entry& b) const {
        if (a.dist != b.dist) return a.dist > b.dist;
        return a.counter > b.counter;
    }
};

class Graph {
public:
    Graph(py::array_t<std::int64_t, py::array::c_style | py::array::forcecast> indptr,
          py::array_t<std::int32_t, py::array::c_style | py::array::forcecast> indices,
          py::array_t<double, py::array::c_style | py::array::forcecast> weights) {
        if (indptr.ndim() != 1 || indices.ndim() != 1 || weights.ndim() != 1)
            throw std::invalid_argument("indptr, indices and weights must be 1-D");
        if (indptr.size() < 1) throw std::invalid_argument("indptr must have n + 1 entries");
        if (indices.size() != weights.size()) throw std::invalid_argument("indices and weights differ in length");
        n_ = static_cast<std::int32_t>(indptr.size() - 1);
        indptr_.assign(indptr.data(), indptr.data() + indptr.size());
        indices_.assign(indices.data(), indices.data() + indices.size());
        weights_.assign(weights.data(), weights.data() + weights.size());
        if (indptr_.front() != 0 || indptr_.back() != static_cast<std::int64_t>(indices_.size()))
            throw std::invalid_argument("indptr does not match indices");
        for (std::int32_t v : indices_)
            if (v < 0 || v >= n_) throw std::invalid_argument("neighbour index out of range");
        for (double w : weights_)
            if (!(w >= 0.0)) throw std::invalid_argument("weights must be non-negative");
    }

    std::int32_t num_nodes() const { return n_; }
    std::size_t num_edges() const { return indices_.size(); }

    // sources: (node, cost) out-edges of the virtual origin, in insertion order, parallel edges already
    // collapsed. targets: (node, cost) edges into the virtual destination. Returns None if unreachable,
    // else (cost, [node, ...]) with the virtual nodes left out.
    std::optional<std::pair<double, std::vector<std::int32_t>>> shortest_path(
        const std::vector<std::pair<std::int32_t, double>>& sources,
        const std::vector<std::pair<std::int32_t, double>>& targets) const {
        const std::int32_t origin = n_, dest = n_ + 1, total = n_ + 2;
        const double inf = std::numeric_limits<double>::infinity();

        std::vector<double> to_dest(n_, inf);
        std::vector<char> has_dest(n_, 0);
        for (const auto& [v, w] : targets) {
            check_node(v);
            if (!has_dest[v] || w < to_dest[v]) to_dest[v] = w;
            has_dest[v] = 1;
        }
        for (const auto& s : sources) check_node(s.first);

        std::vector<double> dist(total, 0.0), seen(total, 0.0);
        std::vector<char> done(total, 0), was_seen(total, 0);
        std::vector<std::int32_t> pred(total, -1);
        std::priority_queue<Entry, std::vector<Entry>, Later> fringe;
        std::uint64_t counter = 0;

        was_seen[origin] = 1;
        fringe.push({0.0, counter++, origin});

        auto relax = [&](std::int32_t v, double dist_v, std::int32_t u, double cost) {
            const double vu = dist_v + cost;
            if (done[u]) return;  // networkx only checks for negative weights here
            if (!was_seen[u] || vu < seen[u]) {
                was_seen[u] = 1;
                seen[u] = vu;
                fringe.push({vu, counter++, u});
                pred[u] = v;
            }
        };

        while (!fringe.empty()) {
            const Entry top = fringe.top();
            fringe.pop();
            const std::int32_t v = top.node;
            if (done[v]) continue;
            done[v] = 1;
            dist[v] = top.dist;
            if (v == dest) break;
            if (v == origin) {
                for (const auto& [u, w] : sources) relax(v, top.dist, u, w);
            } else {
                for (std::int64_t i = indptr_[v]; i < indptr_[v + 1]; ++i) relax(v, top.dist, indices_[i], weights_[i]);
                if (has_dest[v]) relax(v, top.dist, dest, to_dest[v]);
            }
        }
        if (!done[dest]) return std::nullopt;

        std::vector<std::int32_t> path;
        for (std::int32_t v = pred[dest]; v != origin; v = pred[v]) {
            if (v < 0) throw std::logic_error("broken predecessor chain");
            path.push_back(v);
        }
        return std::make_pair(dist[dest], std::vector<std::int32_t>(path.rbegin(), path.rend()));
    }

private:
    void check_node(std::int32_t v) const {
        if (v < 0 || v >= n_) throw std::invalid_argument("node index out of range");
    }

    std::int32_t n_ = 0;
    std::vector<std::int64_t> indptr_;
    std::vector<std::int32_t> indices_;
    std::vector<double> weights_;
};

}  // namespace

PYBIND11_MODULE(_fastroute, m) {
    m.doc() = "C++ Dijkstra for platetrail routing; matches networkx's tie-breaking exactly";
    py::class_<Graph>(m, "Graph")
        .def(py::init<py::array_t<std::int64_t, py::array::c_style | py::array::forcecast>,
                      py::array_t<std::int32_t, py::array::c_style | py::array::forcecast>,
                      py::array_t<double, py::array::c_style | py::array::forcecast>>(),
             py::arg("indptr"), py::arg("indices"), py::arg("weights"))
        .def_property_readonly("num_nodes", &Graph::num_nodes)
        .def_property_readonly("num_edges", &Graph::num_edges)
        .def("shortest_path", &Graph::shortest_path, py::arg("sources"), py::arg("targets"),
             py::call_guard<py::gil_scoped_release>(),
             "Shortest path from a virtual origin (out-edges `sources`) to a virtual destination (in-edges "
             "`targets`). Returns None if unreachable, else (cost, nodes).");
}
