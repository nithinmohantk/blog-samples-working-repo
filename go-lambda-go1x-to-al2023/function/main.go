// Command orderstatus is an API Gateway HTTP API (payload 2.0) handler that
// returns the status of an order. It is deliberately ordinary: the point of the
// sample is how it is built and started, which is all that changes when a
// function moves from the go1.x runtime to provided.al2023.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"regexp"
	"time"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-lambda-go/lambdacontext"
)

// Order is the body returned for a known order.
type Order struct {
	ID        string    `json:"id"`
	Status    string    `json:"status"`
	UpdatedAt time.Time `json:"updatedAt"`
}

// Store looks orders up. The sample uses an in-memory store; a real function
// would hold a DynamoDB or database client here, created once in main.
type Store interface {
	Get(ctx context.Context, id string) (Order, error)
}

var errNotFound = errors.New("order not found")

type memoryStore map[string]Order

func (m memoryStore) Get(ctx context.Context, id string) (Order, error) {
	if err := ctx.Err(); err != nil {
		return Order{}, err
	}
	order, ok := m[id]
	if !ok {
		return Order{}, errNotFound
	}
	return order, nil
}

var validID = regexp.MustCompile(`^ord-[0-9]{6}$`)

// Handler holds what is created once per execution environment.
type Handler struct {
	store  Store
	logger *slog.Logger
}

// Handle answers one request. It never returns a Go error for a bad request:
// an error from the handler becomes a 502 at API Gateway and an error line in
// the logs, which is the wrong signal for a client mistake.
func (h Handler) Handle(ctx context.Context, req events.APIGatewayV2HTTPRequest) (events.APIGatewayV2HTTPResponse, error) {
	log := h.logger
	if lc, ok := lambdacontext.FromContext(ctx); ok {
		log = log.With("requestId", lc.AwsRequestID)
	}
	if deadline, ok := ctx.Deadline(); ok && time.Until(deadline) < 200*time.Millisecond {
		log.Warn("too little time left to answer", "remaining", time.Until(deadline).String())
		return respond(http.StatusServiceUnavailable, map[string]string{"error": "try again"})
	}

	id := req.PathParameters["id"]
	if !validID.MatchString(id) {
		log.Info("rejected order id", "id", id)
		return respond(http.StatusBadRequest, map[string]string{"error": "order id must look like ord-123456"})
	}

	order, err := h.store.Get(ctx, id)
	switch {
	case errors.Is(err, errNotFound):
		return respond(http.StatusNotFound, map[string]string{"error": "no such order"})
	case err != nil:
		log.Error("store lookup failed", "id", id, "error", err)
		return events.APIGatewayV2HTTPResponse{}, err
	}
	log.Info("order returned", "id", id, "status", order.Status)
	return respond(http.StatusOK, order)
}

func respond(status int, body any) (events.APIGatewayV2HTTPResponse, error) {
	payload, err := json.Marshal(body)
	if err != nil {
		return events.APIGatewayV2HTTPResponse{}, err
	}
	return events.APIGatewayV2HTTPResponse{
		StatusCode: status,
		Headers:    map[string]string{"content-type": "application/json"},
		Body:       string(payload),
	}, nil
}

func newHandler() Handler {
	return Handler{
		store: memoryStore{
			"ord-100001": {ID: "ord-100001", Status: "DISPATCHED", UpdatedAt: time.Date(2023, 12, 18, 9, 30, 0, 0, time.UTC)},
			"ord-100002": {ID: "ord-100002", Status: "PICKING", UpdatedAt: time.Date(2023, 12, 19, 14, 5, 0, 0, time.UTC)},
		},
		logger: slog.New(slog.NewJSONHandler(os.Stdout, nil)),
	}
}

func main() {
	lambda.Start(newHandler().Handle)
}
